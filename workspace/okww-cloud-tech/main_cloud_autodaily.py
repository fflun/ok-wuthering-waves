"""Quiet login-triggered launcher. Requires verified background/daily receipts."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from cloud_autorun_state import DailyLedger, ProcessLock, day_key, fingerprint, write_json
from cloud_failure_notice import notification_ready

ROOT=Path(__file__).resolve().parent
STATE=ROOT.parent/'okww-cloud-session/background'


def save_status(value):
    write_json(STATE/'autorun-status.json',value)
    labels={'RUNNING':'正在后台执行任务。','RETRYING':'首次失败，正在自动补做一次。','SUCCEEDED':'本次任务已完成。',
            'SKIPPED':'已有执行记录，本次未重复运行。','DRY_RUN':'启动检查完成，没有启动游戏。',
            'FAILED':'本次运行未完成，已停止自动重试。','NEEDS_ATTENTION':'需要检查，当前未继续执行。',
            'SUCCEEDED_WITH_SKIPS':'日常已完成，陷足流川失败按授权跳过。'}
    text=labels.get(value['status'],value['status'])
    if value.get('day'):text+='\n游戏日：'+value['day']
    if value.get('week'):text+='\n本周刷新日：'+value['week']
    if value.get('completed_stages'):
        stage_labels={'daily':'每日','boss':'战歌重奏','garden':'幻梦游园',
                      'boss_echo':'目标BOSS声骸20次','nest_echo':'全部未完成聚落声骸'}
        text+='\n本次完成：'+'、'.join(stage_labels.get(stage,stage) for stage in value['completed_stages'])
    if value.get('reason'):text+='\n说明：'+value['reason']
    (STATE/'运行状态.txt').write_text(text+'\n',encoding='utf-8')


def run(dry_run=False, task='daily', validate_weekly=False, validate_full=False):
    if validate_full and task!='daily':raise ValueError('Full validation requires the daily chain')
    if validate_weekly and task!='daily':raise ValueError('Weekly validation requires the daily chain')
    config=json.loads((STATE/'autorun-config.json').read_text(encoding='utf-8'))
    notice=json.loads((STATE/'notifications.json').read_text(encoding='utf-8'))
    if not notification_ready(notice):
        raise RuntimeError('No configured failure notification channel; game launch withheld')
    acceptance=json.loads((STATE/'validation.json').read_text(encoding='utf-8'))
    required=('synthetic_capture','game_capture','game_input','no_foreground_interference','native_daily_completed')
    if not all(acceptance.get(key) is True for key in required):
        raise RuntimeError('Background/daily validation is incomplete')
    if acceptance['source_hashes']!=fingerprint(ROOT):
        raise RuntimeError('Automation source changed; revalidation required')
    python=Path(config['python'])
    runtime=Path(config.get('frozen_runtime',str(ROOT.parent/'okww-cloud-runtime-v367')))
    installed_runtime=Path(config['runtime'])
    browser_deps=Path(config['browser_deps'])
    if not python.is_file() or not runtime.is_dir() or not browser_deps.is_dir():
        raise RuntimeError('Configured runtime is unavailable')
    day=day_key()
    ledger=DailyLedger(STATE/'daily-ledger.json')
    from cloud_daily_policy import PendingClaim
    from cloud_failure_notice import notify_retry,notify_recovered
    def on_retry(stage,error):
        save_status({'status':'RETRYING','day':day,'task':stage,'reason':'首次失败，正在从已完成进度补做一次。'})
        notify_retry(STATE,stage,error)
    def on_recovered(stage):notify_recovered(STATE,stage)
    def retry_check():
        PendingClaim(STATE.parent/'claim-pending.json').assert_clear()
        if (STATE/'stop-request').exists():raise RuntimeError('local_stop_request')
    with ProcessLock(STATE/'runner.lock'):
        if task=='daily' and not dry_run and config.get('restart_resume_enabled') is True:
            from cloud_restart_resume import reconcile
            reconcile(ROOT,STATE,config)
        if task=='daily' and (config.get('full_enabled') is True or validate_full):
            from cloud_weekly_state import WeeklyLedger
            from cloud_weekly_chain import execute_stage
            from cloud_full_chain import FullLedger,assert_full_ready,run_full_chain,execute_echo_stage
            from cloud_flow_profiles import plan_flow
            from cloud_small_account_chain import small_account_order
            small_order=small_account_order(config)
            settings=json.loads((ROOT.parent.parent/'configs/cloud-flow-profiles.json').read_text(encoding='utf-8'))
            target=settings['full']['echo_target']
            weekly=WeeklyLedger(STATE/'weekly-ledger.json')
            if dry_run:
                result=dict(plan_flow(ledger,weekly,'full',target),status='DRY_RUN')
                if small_order:
                    result['account_order']=['a',*small_order]
                    result['small_account_modes']={'b':'daily_only','c':'daily_only'}
                save_status(result);return result
            if not validate_full:assert_full_ready(acceptance,config)
            if (STATE.parent/'claim-pending.json').exists():raise RuntimeError('pending_claim_needs_review')
            from cloud_failure_notice import notify_failure
            save_status({'status':'RUNNING','day':day,'task':'full-chain'})
            result=run_full_chain(ledger,weekly,FullLedger(STATE/'full-ledger.json'),
                lambda stage,week,run_id,remaining,timeout:execute_stage(stage,week,run_id,remaining,timeout,config,ROOT,STATE),
                lambda stage,day,run_id,timeout:execute_echo_stage(stage,day,run_id,timeout,config,ROOT,STATE),
                target=target,notify=lambda stage,error:notify_failure(STATE,stage,error),
                daily_retries=config.get('daily_retries',0),retry_check=retry_check,
                stage_retries=config.get('stage_retries',0),on_retry=on_retry,on_recovered=on_recovered)
            if small_order:
                from cloud_small_account_chain import run_scheduled_tail
                result=run_scheduled_tail(result,config,ROOT,STATE)
            save_status(result);return result
        if task=='daily' and (config.get('weekly_enabled') is True or validate_weekly):
            from cloud_weekly_state import WeeklyLedger
            from cloud_weekly_chain import assert_weekly_ready,plan_chain,run_chain,execute_stage
            weekly=WeeklyLedger(STATE/'weekly-ledger.json')
            if dry_run:
                result=dict(plan_chain(ledger,weekly),status='DRY_RUN',weekly_enabled=True)
                save_status(result);return result
            # Explicit manual validation does not enable the logon feature.
            # The installed scheduled task has no --validate-weekly argument.
            if not validate_weekly:assert_weekly_ready(acceptance,config)
            if (STATE.parent/'claim-pending.json').exists():
                raise RuntimeError('pending_claim_needs_review')
            from cloud_failure_notice import notify_failure
            save_status({'status':'RUNNING','day':day,'task':'daily-weekly-chain'})
            result=run_chain(ledger,weekly,
                lambda stage,week,run_id,remaining,timeout:execute_stage(
                    stage,week,run_id,remaining,timeout,config,ROOT,STATE),
                notify=lambda stage,error:notify_failure(STATE,stage,error),
                daily_retries=config.get('daily_retries',0),retry_check=retry_check,
                stage_retries=config.get('stage_retries',0),on_retry=on_retry,on_recovered=on_recovered)
            save_status(result);return result
        records=ledger.read()
        reason='ready'
        if any(item['status']=='RUNNING' for item in records.values()):reason='interrupted_run_needs_review'
        elif task=='daily' and day in records and records[day].get('status')!='READY' and not (config.get('daily_retries')==1 and ledger.retryable(day)):reason='already_attempted'
        if (STATE.parent/'claim-pending.json').exists():reason='pending_claim_needs_review'
        if reason in ('interrupted_run_needs_review','pending_claim_needs_review') and not dry_run:
            raise RuntimeError(reason)
        if dry_run or reason!='ready':
            result={'status':'DRY_RUN' if dry_run else 'SKIPPED','day':day,'reason':reason}
            save_status(result)
            return result
        if task=='daily' and config.get('daily_retries')==1:
            from cloud_daily_retry import run_daily
            from cloud_weekly_chain import execute_stage
            from cloud_autorun_state import week_key
            def boundary():
                if day_key()!=day:raise RuntimeError('Daily refreshed during execution')
            save_status({'status':'RUNNING','day':day,'task':'daily'})
            try:
                receipt=run_daily(ledger,day,lambda owner:execute_stage('daily',week_key(),owner,0,1500,config,ROOT,STATE),
                                  boundary,retries=1,retry_check=retry_check,
                                  on_retry=lambda reason:on_retry('daily',reason),on_recovered=lambda:on_recovered('daily'))
            except BaseException as exc:
                save_status({'status':'FAILED','day':day,'task':task,'reason':str(exc)})
                raise
            result={'status':'SUCCEEDED','day':day,'task':'daily','receipt':receipt}
            save_status(result);return result
        if task=='daily':
            allowed,reason=ledger.begin(day)
            if not allowed:raise RuntimeError(reason)
        started=time.time()
        env=dict(os.environ,PYTHONPATH=os.pathsep.join((str(browser_deps),str(runtime),str(installed_runtime))),
                 OKWW_INSTALLED_RUNTIME=str(runtime),PYTHONIOENCODING='utf-8')
        save_status({'status':'RUNNING','day':day,'started_at':started})
        try:
            suffix=day if task=='daily' else str(time.time_ns())
            with (STATE/(task+'-'+suffix+'.log')).open('w',encoding='utf-8') as log:
                command=[str(python),'-u',str(ROOT/'main_cloud_daily.py'),
                    '--connect','--background','--allow-game-tasks']
                command+=['--once-daily'] if task=='daily' else ['--task',task]
                child=subprocess.Popen(command,
                    cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
                try:
                    child.wait(timeout=1500)
                except BaseException:
                    # Bound startup stalls too; stop only this owned process tree.
                    subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
                    raise
            receipt=json.loads((STATE/(task+'-result.json')).read_text(encoding='utf-8'))
            if child.returncode!=0 or receipt.get('status')!='SUCCEEDED' or receipt.get('completed_at',0)<started:
                raise RuntimeError(f'{task} did not finish successfully; inspect its run log')
            if task=='daily':ledger.finish(day,'SUCCEEDED')
            result={'status':'SUCCEEDED','day':day,'task':task}
        except BaseException as exc:
            if task=='daily':ledger.finish(day,'FAILED',str(exc))
            save_status({'status':'FAILED','day':day,'task':task,'reason':str(exc)})
            raise
        save_status(result)
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--plan-weekly',action='store_true',help='Read-only weekly plan; never starts a game')
    parser.add_argument('--validate-weekly',action='store_true',help='Explicit supervised game run; does not enable logon weekly tasks')
    parser.add_argument('--validate-full',action='store_true',help='Explicit supervised full game flow; does not enable it at logon')
    parser.add_argument('--task',choices=('daily','nightmare','echo','tacet','forgery','simulation'),default='daily')
    options=parser.parse_args()
    try:
        if options.plan_weekly:
            from cloud_weekly_chain import plan_chain
            from cloud_weekly_state import WeeklyLedger
            result=plan_chain(DailyLedger(STATE/'daily-ledger.json'),WeeklyLedger(STATE/'weekly-ledger.json'))
            result['weekly_enabled']=json.loads((STATE/'autorun-config.json').read_text(encoding='utf-8')).get('weekly_enabled',False)
            print(json.dumps(result,ensure_ascii=False,indent=2))
        else:run(options.dry_run,options.task,options.validate_weekly,options.validate_full)
    except Exception as exc:
        if not options.plan_weekly:
            save_status({'status':'NEEDS_ATTENTION','task':getattr(exc,'stage',options.task),'reason':str(exc)})
        else:print(json.dumps({'status':'PLAN_ERROR','error':str(exc)},ensure_ascii=False))
        if not (options.dry_run or options.plan_weekly or getattr(exc,'notified',False)):
            from cloud_failure_notice import notify_failure
            notify_failure(STATE,getattr(exc,'stage',options.task),str(exc))
        raise SystemExit(1)
