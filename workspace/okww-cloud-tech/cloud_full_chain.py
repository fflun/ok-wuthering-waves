"""Daily/weekly plus bounded echo-only stages, with per-day receipts."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from cloud_autorun_state import day_key, write_json
from cloud_weekly_chain import run_chain, local_now, WeeklyChainError

ECHO_LIMIT = 2700
TOTAL_LIMIT = 10800


class FullLedger:
    def __init__(self, path): self.path = Path(path)
    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
    def retryable(self,day,stage):
        old=self.read().get(day,{}).get(stage,{})
        return old.get('status')=='FAILED' and old.get('retry_allowed') is True and old.get('attempt_count',1)<2
    def begin(self, day, stage, run_id, started,retry_failed=False):
        records = self.read()
        if any(r.get('status') == 'RUNNING' for stages in records.values() for r in stages.values()):
            raise RuntimeError('Interrupted full flow needs review')
        old = records.get(day, {}).get(stage, {})
        if old.get('status') in ('SUCCEEDED','SKIPPED_ALLOWED_FAILURE'): return False
        if old.get('status') == 'FAILED' and not (retry_failed and self.retryable(day,stage)): raise RuntimeError('Full flow failure needs review')
        history=old.get('history',[])
        if old:history=history+[{k:v for k,v in old.items() if k!='history'}]
        records.setdefault(day, {})[stage] = dict(status='RUNNING', run_id=run_id, started_at=started,
            attempt_count=old.get('attempt_count',1)+1 if old else 1,history=history)
        write_json(self.path, records)
        return True
    def finish(self, day, stage, run_id, receipt):
        records = self.read(); item = records[day][stage]
        if item['status'] != 'RUNNING' or item['run_id'] != run_id:
            raise RuntimeError('Full flow receipt is unowned')
        allowed_skip=receipt.get('status')=='SKIPPED_ALLOWED_FAILURE'
        if allowed_skip:
            from cloud_final_nest_policy import validate_final_skip
            if stage!='nest_echo':raise RuntimeError('Only the final nest may be skipped')
            validate_final_skip(receipt)
        if (receipt.get('status') not in ('SUCCEEDED','SKIPPED_ALLOWED_FAILURE') or receipt.get('run_id') != run_id
                or receipt.get('game_day') != day or receipt.get('completed_at', 0) < item['started_at']):
            raise RuntimeError('Full flow receipt is stale or incomplete')
        if stage == 'boss_echo' and receipt.get('combats_completed') != 20:
            raise RuntimeError('Full flow requires twenty completed boss fights')
        if stage == 'nest_echo' and not allowed_skip and receipt.get('catalog_complete') is not True:
            raise RuntimeError('Full nest catalog and pickups are not complete')
        item.update(status=receipt['status'], receipt=receipt)
        write_json(self.path, records)
    def accept_failed_final_skip(self,day,receipt):
        from cloud_final_nest_policy import validate_final_skip
        validate_final_skip(receipt)
        records=self.read();item=records[day]['nest_echo']
        if (item.get('status')!='FAILED' or item.get('run_id')!=receipt['run_id'] or receipt['game_day']!=day
                or receipt['completed_at']<item['started_at']):
            raise RuntimeError('Historical final-nest failure is not owned')
        item.setdefault('history',[]).append({k:v for k,v in item.items() if k!='history'})
        item.update(status=receipt['status'],receipt=receipt,retry_allowed=False,policy_accepted_at=time.time())
        write_json(self.path,records)
    def fail(self, day, stage, run_id, error,retry_allowed=False):
        records = self.read(); item = records[day][stage]
        if item['status'] != 'RUNNING' or item['run_id'] != run_id:
            raise RuntimeError('Full flow failure is unowned')
        item.update(status='FAILED', error=str(error), failed_at=time.time(),retry_allowed=retry_allowed)
        write_json(self.path, records)


def assert_full_ready(acceptance, config):
    trial = config.get('full_trial_enabled') is True and acceptance.get('full_chain_offline_verified') is True
    if not trial and acceptance.get('full_chain_live_verified') is not True:
        raise RuntimeError('Full daily/weekly/echo flow has not passed live acceptance')
    if not trial and acceptance.get('weekly_chain_live_verified') is not True:
        raise RuntimeError('Weekly flow has not passed live acceptance')
    if config.get('full_scheduler_timeout_seconds', 0) < TOTAL_LIMIT:
        raise RuntimeError('Full flow requires a reviewed three-hour scheduler limit')


def run_full_chain(daily, weekly, full, execute_base, execute_echo, target='both', notify=None, now=local_now,daily_retries=0,retry_check=None,stage_retries=0,on_retry=None,on_recovered=None):
    if target not in ('boss', 'nests', 'both'): raise ValueError('Invalid echo target')
    if stage_retries not in (0,1):raise ValueError('Follow-up stages permit at most one retry')
    started = time.monotonic(); day = day_key(now())
    records = full.read()
    if any(r.get('status') == 'RUNNING' for stages in records.values() for r in stages.values()):
        raise RuntimeError('Interrupted full flow needs review')
    result = run_chain(daily, weekly, execute_base, notify=notify, now=now,daily_retries=daily_retries,retry_check=retry_check,
                       stage_retries=stage_retries,on_retry=on_retry,on_recovered=on_recovered)
    if result['status'] == 'NEEDS_ATTENTION': return result
    ran = list(result['completed_stages'])
    stages = {'boss': ('boss_echo',), 'nests': ('nest_echo',), 'both': ('boss_echo', 'nest_echo')}[target]
    for stage in stages:
        if day_key(now()) != day: raise RuntimeError('Game day refreshed; full flow stopped')
        if time.monotonic() - started >= TOTAL_LIMIT: raise RuntimeError('Full flow exceeded its time limit')
        for _ in range(stage_retries+1):
            if day_key(now())!=day or time.monotonic()-started>=TOTAL_LIMIT:
                raise RuntimeError('Game day refreshed or full-flow time limit reached')
            if retry_check:retry_check()
            if _==0 and full.retryable(day,stage) and on_retry:
                try:on_retry(stage,'Resuming the recorded first failure')
                except Exception:pass
            run_id=uuid.uuid4().hex
            try:
                if not full.begin(day,stage,run_id,now().timestamp(),retry_failed=stage_retries==1):break
            except Exception as exc:raise WeeklyChainError(stage,result['week'],exc) from exc
            validating=False
            try:
                receipt=execute_echo(stage,day,run_id,min(ECHO_LIMIT,TOTAL_LIMIT-(time.monotonic()-started)))
                validating=True
                if day_key(now())!=day:raise RuntimeError('Game day refreshed; full flow stopped')
                full.finish(day,stage,run_id,receipt)
                if receipt['status']=='SUCCEEDED':ran.append(stage)
                if receipt['status']=='SUCCEEDED' and full.read()[day][stage]['attempt_count']>1 and on_recovered:
                    try:on_recovered(stage)
                    except Exception:pass
                break
            except BaseException as exc:
                safe=isinstance(exc,Exception) and getattr(exc,'retry_allowed',True) and not validating
                safe=safe and day_key(now())==day and time.monotonic()-started<TOTAL_LIMIT
                try:
                    if retry_check:retry_check()
                except Exception:safe=False
                remaining=full.read()[day][stage].get('attempt_count',1)<stage_retries+1
                full.fail(day,stage,run_id,exc,retry_allowed=safe and remaining)
                if safe and remaining:
                    if on_retry:
                        try:on_retry(stage,str(exc))
                        except Exception:pass
                    continue
                notified=False
                if notify:
                    try:notify(stage,str(exc));notified=True
                    except Exception:pass
                raise WeeklyChainError(stage,result['week'],exc,notified) from exc
    skips=[full.read()[day][stage]['receipt'] for stage in stages
           if full.read()[day].get(stage,{}).get('status')=='SKIPPED_ALLOWED_FAILURE']
    result.update(status='SUCCEEDED_WITH_SKIPS' if skips else ('SUCCEEDED' if ran else 'SKIPPED'),
                  mode='full',completed_stages=ran,allowed_skips=skips)
    return result


def execute_echo_stage(stage, day, run_id, timeout, config, root, state):
    root, state = Path(root), Path(state)
    out = root.parent.parent / 'outputs' / ('full-' + day + '-' + stage + '-' + run_id)
    out.mkdir(parents=True, exist_ok=False)
    frozen = config.get('frozen_runtime', str(root.parent / 'okww-cloud-runtime-v367'))
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((config['browser_deps'], frozen, config['runtime'])),
               OKWW_INSTALLED_RUNTIME=frozen, PYTHONIOENCODING='utf-8', OKWW_RUN_ID=run_id,
               OKWW_FULL_RUN_ID=run_id, OKWW_FULL_STAGE=stage, OKWW_FULL_DAY=day, OKWW_HEAL_DEEPSEEK='1')
    if config.get('restart_resume_enabled') is True:env['OKWW_RESTART_RECHECK']='1'
    # Echo-only children never inherit weekly material claim ownership.
    for key in ('OKWW_WEEKLY_LEDGER', 'OKWW_WEEKLY_RUN_ID', 'OKWW_WEEKLY_WEEK', 'OKWW_WEEKLY_OUTPUT'):
        env.pop(key, None)
    command = [config['python'], '-u', str(root / 'main_cloud_full_echo.py'), '--stage', stage, '--output', str(out)]
    with (out / 'run.log').open('w', encoding='utf-8') as log:
        child = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        try: child.wait(timeout=timeout)
        except BaseException:
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            raise
    if child.returncode != 0:
        if stage=='nest_echo':
            from cloud_final_nest_policy import collect_final_skip
            skipped=collect_final_skip(day,run_id,out,state,config)
            if skipped:return skipped
        from cloud_daily_retry import DailyStageFailure
        name='echo' if stage=='boss_echo' else 'nightmare'
        path=state/(name+'-result.json')
        failed=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        safe=failed.get('status')=='FAILED' and failed.get('run_id')==run_id and failed.get('retry_allowed') is True
        raise DailyStageFailure('Echo stage failed; retained evidence: '+str(out),retry_allowed=safe)
    return collect_echo_receipt(stage,day,run_id,out,state)


def collect_echo_receipt(stage,day,run_id,out,state):
    """Reconcile a finished owned child without launching another battle."""
    out,state=Path(out),Path(state)
    events = [json.loads(line) for line in (out / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    completed = [e for e in events if e.get('event') == 'batch_succeeded']
    if len(completed) != 1: raise RuntimeError('Echo stage has no unique completion evidence')
    name = 'echo' if stage == 'boss_echo' else 'nightmare'
    native = json.loads((state / (name + '-result.json')).read_text(encoding='utf-8'))
    if native.get('status') != 'SUCCEEDED' or native.get('run_id') != run_id:
        raise RuntimeError('Native echo receipt is stale or unowned')
    done = completed[0]
    if day_key(datetime.fromtimestamp(done['at'], timezone.utc)) != day:
        raise RuntimeError('Echo completion belongs to another game day')
    receipt = dict(status='SUCCEEDED', run_id=run_id, game_day=day, completed_at=done['at'],
                   evidence_directory=str(out), stamina_claims=0)
    if stage == 'boss_echo':
        fights = [e['round'] for e in events if e.get('event') == 'combat_returned']
        if done.get('progress_file'):
            from cloud_echo_progress import verified_boss_progress
            path=state/f'boss-echo-progress-{day}.json'
            if Path(done['progress_file']).resolve()!=path.resolve():raise RuntimeError('Boss progress path is not owned')
            progress=verified_boss_progress(path,day)
            receipt['progress_file']=str(path)
            receipt['absorbed_count']=sum(r['absorbed'] for r in progress['rounds'])
        elif fights != list(range(1, 21)): raise RuntimeError('Twenty boss victories are not verified')
        receipt.update(combats_completed=20, native_info=done.get('info', {}),
                       pickup_verification='native results; full live acceptance remains required')
    else:
        if not done.get('catalog') or any(v[0] != v[1] for v in done['catalog'].values()):
            raise RuntimeError('Nest catalog is empty or unfinished')
        results=done.get('pickup_results')
        if results is not None:
            if set(results)!=set(done['finished']) or any(v.get('search_completed') is not True for v in results.values()):
                raise RuntimeError('Nest pickup search checkpoints incomplete')
            from cloud_nest_state import OPTIONAL_PICKUP_TARGET
            if any(v.get('unconfirmed_allowed') and (name!=OPTIONAL_PICKUP_TARGET or v['absorbed'])
                   for name,v in results.items()):
                raise RuntimeError('Unconfirmed pickup policy escaped the final nest')
            receipt.update(verified_pickups=[name for name,v in results.items() if v['absorbed']],
                searched_no_echo=[name for name,v in results.items() if not v['absorbed'] and not v.get('unconfirmed_allowed')],
                pickup_unconfirmed_allowed=[name for name,v in results.items() if v.get('unconfirmed_allowed')],
                pickup_searches_completed=done['finished'])
        else:receipt['verified_pickups']=done['finished']
        receipt.update(catalog_complete=True, catalog=done['catalog'])
    return receipt
