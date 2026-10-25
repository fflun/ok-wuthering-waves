"""Opt-in daily/weekly sequencing. Planning never launches a browser."""
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from cloud_autorun_state import day_key,week_key
from cloud_weekly_state import WeeklyLedger

LIMITS={'daily':1500,'boss':1500,'garden':2100}
TOTAL_LIMIT=5400


def local_now():return datetime.now(timezone(timedelta(hours=8)))


class WeeklyChainError(RuntimeError):
    def __init__(self,stage,week,error,notified=False):
        self.stage=stage;self.week=week;self.notified=notified
        super().__init__(f'{stage} [{week}]: {error}')


def assert_weekly_ready(acceptance,config):
    if config.get('weekly_enabled') is not True:raise RuntimeError('Weekly chain is disabled')
    if acceptance.get('weekly_chain_live_verified') is not True:
        raise RuntimeError('Full weekly chain has not passed live acceptance')
    if config.get('weekly_scheduler_timeout_seconds',0)<TOTAL_LIMIT:
        raise RuntimeError('Weekly chain requires a reviewed 90-minute scheduler limit')


def plan_chain(daily,weekly,now=None,daily_retries=0,stage_retries=0):
    now=now or local_now();day=day_key(now);week=week_key(now)
    days=daily.read();stages=weekly.read().get(week,{})
    blocked=None
    if any(item.get('status')=='RUNNING' for item in days.values()) or weekly.blocked():
        blocked='interrupted_run_needs_review'
    elif days.get(day,{}).get('status') not in (None,'SUCCEEDED','READY') and not (daily_retries==1 and daily.retryable(day)):
        blocked='daily_failure_needs_review'
    elif any(item.get('status')=='FAILED' and not (stage_retries==1 and weekly.retryable(week,stage)) for stage,item in stages.items()):
        blocked='weekly_failure_needs_review'
    actions=[]
    actions.append(dict(stage='daily',action='skip' if days.get(day,{}).get('status')=='SUCCEEDED' else 'run'))
    for stage in ('boss','garden'):
        item=stages.get(stage,{})
        action='skip' if item.get('status')=='SUCCEEDED' else 'run'
        if blocked and action=='run':action='blocked'
        data=dict(stage=stage,action=action)
        if stage=='boss':data['remaining_claims']=max(0,3-len(item.get('claims',[])))
        actions.append(data)
    return dict(day=day,week=week,blocked=blocked,actions=actions,
                stage_limits_seconds=LIMITS,required_scheduler_seconds=TOTAL_LIMIT)


def run_chain(daily,weekly,execute,notify=None,now=local_now,daily_retries=0,retry_check=None,stage_retries=0,on_retry=None,on_recovered=None):
    """Caller holds the shared process lock. Execute returns owned receipts."""
    if stage_retries not in (0,1):raise ValueError('Weekly permits at most one retry')
    plan=plan_chain(daily,weekly,now(),daily_retries,stage_retries);day,week=plan['day'],plan['week']
    deadline=time.monotonic()+TOTAL_LIMIT
    def error(stage,exc):
        notified=False
        if notify:
            try:notify(stage,str(exc));notified=True
            except Exception:pass
        return WeeklyChainError(stage,week,exc,notified)
    def boundary():
        current=now()
        if day_key(current)!=day or week_key(current)!=week:
            raise RuntimeError('Game refresh occurred; stop for review')
        if time.monotonic()>=deadline:raise RuntimeError('Weekly chain exceeded its total time limit')
    weekly_failed=plan['blocked']=='weekly_failure_needs_review'
    if plan['blocked'] and not weekly_failed:raise error('preflight',plan['blocked'])
    ran=[]
    for action in plan['actions']:
        stage=action['stage']
        if weekly_failed and stage!='daily':continue
        if action['action']=='skip':continue
        try:boundary()
        except Exception as exc:raise error(stage,exc) from exc
        run_id=uuid.uuid4().hex
        if stage=='daily':
            from cloud_daily_retry import run_daily
            try:
                run_daily(daily,day,lambda owner:execute('daily',week,owner,0,
                    min(LIMITS['daily'],max(1,deadline-time.monotonic()))),boundary,
                    retries=daily_retries,retry_check=retry_check,
                    on_retry=(lambda reason:on_retry('daily',reason)) if on_retry else None,
                    on_recovered=(lambda:on_recovered('daily')) if on_recovered else None)
            except BaseException as exc:raise error(stage,exc) from exc
            ran.append(stage)
            continue
        for _ in range(stage_retries+1):
            boundary()
            if retry_check:retry_check()
            if _==0 and weekly.retryable(week,stage) and on_retry:
                try:on_retry(stage,'Resuming the recorded first failure')
                except Exception:pass
            run_id=uuid.uuid4().hex
            try:
                if not weekly.begin(week,stage,run_id,now().timestamp(),retry_failed=stage_retries==1):break
            except Exception as exc:raise error(stage,exc) from exc
            validating=False
            try:
                remaining=max(0,3-len(weekly.read()[week][stage].get('claims',[]))) if stage=='boss' else 0
                if stage=='boss' and remaining==0:
                    receipt=dict(status='SUCCEEDED',run_id=run_id,game_week=week,completed_at=now().timestamp(),
                                 source='three material claim receipts already verified')
                else:
                    receipt=execute(stage,week,run_id,remaining,min(LIMITS[stage],max(1,deadline-time.monotonic())))
                validating=True;boundary()
                weekly.finish(week,stage,run_id,receipt);ran.append(stage)
                if weekly.read()[week][stage].get('attempt_count',1)>1 and on_recovered:
                    try:on_recovered(stage)
                    except Exception:pass
                break
            except BaseException as exc:
                safe=isinstance(exc,Exception) and getattr(exc,'retry_allowed',True) and not validating
                try:
                    boundary()
                    if retry_check:retry_check()
                except Exception:safe=False
                remaining=weekly.read()[week][stage].get('attempt_count',1)<stage_retries+1
                weekly.fail(week,stage,run_id,exc,retry_allowed=safe and remaining)
                if safe and remaining:
                    if on_retry:
                        try:on_retry(stage,str(exc))
                        except Exception:pass
                    continue
                raise error(stage,exc) from exc
    return dict(status='NEEDS_ATTENTION' if weekly_failed else ('SUCCEEDED' if ran else 'SKIPPED'),
                day=day,week=week,completed_stages=ran,
                reason='weekly_failure_needs_review' if weekly_failed else ('completed' if ran else 'already_completed'))


def execute_stage(stage,week,run_id,remaining,timeout,config,root,state,account=None):
    root,state=Path(root),Path(state)
    frozen=Path(config.get('frozen_runtime',str(root.parent/'okww-cloud-runtime-v367')))
    if account is not None and (account not in ('b','c') or stage!='daily'):
        raise ValueError('Small accounts support daily only')
    out=root.parent.parent/'outputs'/('scheduled-'+(account+'-' if account else '')+week+'-'+stage+'-'+run_id)
    out.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,PYTHONPATH=os.pathsep.join((config['browser_deps'],str(frozen),config['runtime'])),
        OKWW_INSTALLED_RUNTIME=str(frozen),PYTHONIOENCODING='utf-8',OKWW_RUN_ID=run_id)
    if config.get('restart_resume_enabled') is True:env['OKWW_RESTART_RECHECK']='1'
    command=[config['python'],'-u',str(root/'main_cloud_daily.py'),
             '--connect','--background','--allow-game-tasks']
    if account:command+=['--account',account]
    if stage=='daily':
        command+=['--once-daily'];result_name='daily'
        env['OKWW_DAILY_OUTPUT']=str(out)
        from cloud_autorun_state import DailyLedger
        record=DailyLedger(state/'daily-ledger.json').read().get(day_key(),{})
        env['OKWW_DAILY_RETRY']='1' if record.get('attempt_count',1)>1 else '0'
    else:
        env.update(OKWW_WEEKLY_WEEK=week,OKWW_WEEKLY_RUN_ID=run_id,
                   OKWW_WEEKLY_LEDGER=str(state/'weekly-ledger.json'),OKWW_WEEKLY_OUTPUT=str(out))
        if stage=='boss':
            if remaining not in (1,2,3):raise RuntimeError('Weekly remaining claims are invalid')
            command+=['--task','echo','--weekly-rounds',str(remaining)];result_name='echo'
        else:
            command+=['--task','garden'];result_name='garden';env['OKWW_GARDEN_OUTPUT']=str(out)
    started=time.time()
    with (out/'run.log').open('w',encoding='utf-8') as log:
        child=subprocess.Popen(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        try:child.wait(timeout=timeout)
        except BaseException:
            subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
            raise
    from cloud_daily_retry import DailyStageFailure
    result_path=state/(result_name+'-result.json')
    receipt=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
    if (child.returncode!=0 or receipt.get('status')!='SUCCEEDED' or receipt.get('run_id')!=run_id
            or receipt.get('completed_at',0)<started):
        message='Native stage did not return a fresh successful receipt; '+str(out)
        safe=child.returncode!=0 and receipt.get('status')=='FAILED' and receipt.get('run_id')==run_id and receipt.get('at',0)>=started and receipt.get('retry_allowed') is True
        raise DailyStageFailure(message,retry_allowed=safe)
    if stage=='daily':
        from datetime import datetime,timezone
        verified=receipt.get('daily_verification') or {}
        expected_day=day_key(datetime.fromtimestamp(started,timezone.utc))
        if (verified.get('complete') is not True or verified.get('game_day')!=expected_day
                or verified.get('activity',0)<100 or verified.get('verified_rewards')!=5
                or verified.get('verified_at',0)<started):
            raise DailyStageFailure('Daily completion lacks fresh activity/reward evidence')
        from cloud_daily_closure import complete
        if (verified.get('all_daily_complete') is not True
                or not complete(verified.get('closure'),expected_day)
                or verified['closure'].get('verified_at',0)<started):
            raise DailyStageFailure('Daily completion lacks fresh mandatory mail/radio evidence')
    if stage=='garden':
        receipt=json.loads((state/'garden-state.json').read_text(encoding='utf-8'))
        if receipt.get('run_id')!=run_id or receipt.get('completed_at',0)<started:
            raise RuntimeError('Garden reward receipt is stale')
    elif stage=='boss':
        if receipt.get('verified_weekly_claims')!=remaining:raise RuntimeError('Weekly native claim count is incomplete')
    receipt=dict(receipt,game_week=receipt.get('game_week',week),evidence_directory=str(out))
    return receipt
