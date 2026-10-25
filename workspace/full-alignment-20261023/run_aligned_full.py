"""One authorized A-only Linux run, using the existing native daily/echo flows."""
import fcntl,json,os,signal,subprocess,sys,time,uuid
from pathlib import Path
from contextlib import contextmanager
ROOT=Path('/opt/cloudgames/wuwa-20261023')
CODE=ROOT/'code'
STATE=ROOT/'okww-cloud-session/background'
OUT=Path('/opt/cloudgames/full-alignment-20261023')
sys.path.insert(0,str(CODE))
from cloud_autorun_state import day_key,week_key,write_json,ProcessLock,DailyLedger
from cloud_full_chain import FullLedger,collect_echo_receipt
from cloud_restart_resume import assert_controls
from cloud_final_nest_policy import collect_final_skip
from stage_control_boundary import check_controls
from owned_cloud_session import OwnedSession
from full_replay_checkpoints import read_verified,save_verified
from stage_policy import WorkflowStopped,run_plan,completed_weekly


def validate_daily(r,owner,day,started):
    v=r.get('daily_verification') or {}
    if (r.get('status')!='SUCCEEDED' or r.get('run_id')!=owner
        or r.get('completed_at',0)<started or v.get('game_day')!=day
        or v.get('all_daily_complete') is not True or v.get('verified_rewards')!=5
        or (v.get('closure') or {}).get('complete') is not True):
        raise RuntimeError('Daily receipt incomplete, stale, or unowned')
    return r


@contextmanager
def sequence_guard():
    lock_path=Path('/run/lock/cloudgames-sequential.lock')
    owner=os.environ.get('CLOUDGAMES_SEQUENCE_OWNER')
    if owner:
        assert owner.isdigit(), 'Invalid sequence owner'
        st=lock_path.stat()
        expected=f'{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}'
        held=any(len(v:=line.split())>=6 and v[1]=='FLOCK' and v[3]=='WRITE'
                 and v[4]==owner and v[5]==expected for line in Path('/proc/locks').read_text().splitlines())
        cmd=Path('/proc')/owner/'cmdline'
        assert held and b'/opt/cloudgames/bin/sequential_daily.py' in cmd.read_bytes().split(b'\0'), 'Queue lock ownership unverified'
        yield
    else:
        with lock_path.open('a') as seq:
            fcntl.flock(seq,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield


def main():
    OUT.mkdir(exist_ok=True)
    with sequence_guard(), ProcessLock(STATE/'runner.lock'):
        day=day_key()
        replay_weekly=day=='2026-10-23' and '--weekly-replay' in sys.argv
        started=time.time();deadline=time.monotonic()+10800
        status={'status':'RUNNING','game_day':day,'pid':os.getpid(),'started_at':started,'stages':{}}
        def save():write_json(OUT/'status.json',status)
        def boundary(*, child_active=False):
            if day_key()!=day:raise WorkflowStopped('Game day refreshed')
            if time.monotonic()>=deadline:raise WorkflowStopped('Full workflow time limit')
            try:check_controls(STATE, child_active=child_active)
            except Exception as exc:raise WorkflowStopped(str(exc)) from exc
        def execute(stage,owner,args,limit):
            boundary()
            session.assert_alive()
            folder=OUT/(stage+'-'+owner);folder.mkdir(exist_ok=False)
            env=dict(os.environ,OKWW_RUN_ID=owner,OKWW_DAILY_OUTPUT=str(folder),
                     OKWW_RESTART_RECHECK='1',OKWW_ALLOW_OWNED_SOLVENT_REFILL='1',PYTHONDONTWRITEBYTECODE='1')
            for key in ('OKWW_FULL_RUN_ID','OKWW_FULL_STAGE','OKWW_FULL_DAY','OKWW_ATTACH_OWNED_SESSION'):
                env.pop(key,None)
            env['OKWW_ATTACH_OWNED_SESSION']='1'
            echo_stage=stage in ('boss_echo','nest_echo')
            if echo_stage:
                env.update(OKWW_FULL_RUN_ID=owner,OKWW_FULL_STAGE=stage,OKWW_FULL_DAY=day)
            if stage.startswith('weekly_probe') or stage=='weekly_materials':
                env.update(OKWW_WEEKLY_OUTPUT=str(folder),OKWW_WEEKLY_WEEK=week_key(),
                           OKWW_WEEKLY_RUN_ID=owner,OKWW_WEEKLY_LEDGER=str(STATE/'weekly-ledger.json'))
            if stage.startswith('weekly_probe'):
                env['OKWW_WEEKLY_REPLAY_STAGE']=stage
            if stage=='garden':
                env.update(OKWW_GARDEN_OUTPUT=str(folder),OKWW_WEEKLY_WEEK=week_key())
                if replay_weekly:env['OKWW_GARDEN_REPLAY_ONCE']=day
            command=[sys.executable,'-u',str(CODE/args[0]),*args[1:]]
            if echo_stage:command+=['--output',str(folder)]
            with (folder/'run.log').open('w') as log:
                child=subprocess.Popen(command,cwd=CODE,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                status['current']={'stage':stage,'owner':owner,'pid':child.pid,'started_at':time.time(),'output':str(folder)};save()
                end=time.monotonic()+limit
                try:
                    while child.poll() is None:
                        boundary(child_active=True)
                        if time.monotonic()>=end:raise RuntimeError('Stage exceeded native bounded duration')
                        time.sleep(2)
                except BaseException:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=30)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    raise
            boundary()
            if stage.startswith('weekly_probe'):
                r=json.loads((STATE/'echo-result.json').read_text())
                if (r.get('run_id')!=owner or 'WEEKLY_PROBE_ONLY:' not in (str(r.get('error',''))+' '+str(r.get('native_error','')))
                    or not (folder/'weekly-reward-probe.png').is_file()
                    or not (folder/'weekly-reward-probe.json').is_file()):
                    raise RuntimeError('Weekly replay did not reach its verified no-claim probe')
                endpoint=json.loads((folder/'weekly-probe-complete.json').read_text())
                assert endpoint.get('status')=='REPLAY_ENDPOINT_VERIFIED' and endpoint.get('run_id')==owner
                assert endpoint.get('game_day')==day and endpoint.get('exit_verified') is True and endpoint.get('reward_claimed') is False
                import hashlib
                for image in endpoint['quota_images']+[endpoint['world_image']]:
                    assert hashlib.sha256(Path(image['path']).read_bytes()).hexdigest()==image['sha256']
                return {'status':'REPLAY_PROBE_VERIFIED','run_id':owner,'game_day':day,'endpoint':endpoint,
                        'reward_claimed':False,'evidence_directory':str(folder),'completed_at':time.time()}
            if child.returncode:
                if stage=='nest_echo' and (folder/'events.jsonl').is_file():
                    config=json.loads((STATE/'autorun-config.json').read_text())
                    receipt=collect_final_skip(day,owner,folder,STATE,config)
                    if receipt:return receipt
                raise RuntimeError(f'{stage} failed; new evidence retained in {folder}')
            if stage=='daily_probe':
                receipt=json.loads((STATE/'daily-probe-result.json').read_text())
                v=receipt.get('daily_verification') or {}
                assert receipt.get('status')=='SUCCEEDED' and receipt.get('run_id')==owner
                assert v.get('game_day')==day and receipt.get('completed_at',0)>status['current']['started_at']
                spent=receipt.get('info',{}).get('current daily progress')
                assert isinstance(spent,(int,float)) and spent>=120, 'Spent-120 checkpoint could not be reconciled'
                write_json(folder/'native-result.json',receipt)
                return receipt
            if stage=='daily':
                receipt=json.loads((STATE/'daily-result.json').read_text())
                write_json(folder/'native-result.json',receipt)
                return validate_daily(receipt,owner,day,status['current']['started_at'])
            if stage=='garden':
                r=json.loads((STATE/'garden-state.json').read_text())
                assert r['run_id']==owner and r['game_week']==week_key()
                assert r['status']=='SUCCEEDED' and r['current']==6000 and r['verified_rewards']==6
                if replay_weekly:
                    events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
                    assert any(e.get('event')=='authorized_completed_garden_replay' for e in events)
                    assert any(e.get('event')=='garden_result' for e in events),'Replay never reached a game result'
                return r
            if stage=='weekly_materials':
                r=json.loads((STATE/'echo-result.json').read_text())
                assert r['status']=='SUCCEEDED' and r['run_id']==owner
                return r
            return collect_echo_receipt(stage,day,owner,folder,STATE)
        save()
        session=OwnedSession(OUT,STATE)
        try:
            boundary()
            status['session']=session.start(boundary);save()
            from cloud_weekly_state import WeeklyLedger
            reference=json.loads((Path('/opt/cloudgames/full-alignment-20261023')/'weekly-reference.json').read_text(encoding='utf8'))
            registry=json.loads((STATE/'accounts/registry.json').read_text(encoding='utf8'))
            identity=next(a['expected_uid_hash'] for a in registry['accounts'] if a['id']=='a')
            if not identity or reference.get('account_hash')!=identity:
                raise WorkflowStopped('Account evidence does not match the configured account')
            daily=DailyLedger(STATE/'daily-ledger.json')
            weekly=WeeklyLedger(STATE/'weekly-ledger.json')
            full=FullLedger(STATE/'full-ledger.json')
            def daily_action():
                try:
                    if daily.read().get(day,{}).get('status')!='SUCCEEDED':
                        permitted,reason=daily.begin(day)
                        if not permitted:raise RuntimeError(reason)
                        owner=uuid.uuid4().hex;daily.own(day,owner)
                        try:
                            receipt=execute('daily',owner,['main_cloud_daily.py','--account','a','--connect','--background','--allow-game-tasks','--once-daily'],1500)
                            daily.finish(day,'SUCCEEDED',receipt=receipt)
                        except BaseException as exc:
                            daily.finish(day,'FAILED',str(exc),retry_allowed=False);raise
                    record=daily.read()[day]
                    validate_daily(record['receipt'],record['run_id'],day,0)
                    return record
                finally:
                    status['stages']['daily']=daily.read().get(day,{})
                    save()
            def weekly_action(name):
                def action():
                    try:
                        cached=completed_weekly(weekly,week_key(),name)
                        if cached is not None:
                            status.setdefault('weekly_cache_hits',{})[name]=week_key()
                            return cached
                        owner=uuid.uuid4().hex
                        if weekly.begin(week_key(),name,owner,time.time()):
                            try:
                                if name=='boss':
                                    remaining=3-len(weekly.read()[week_key()][name].get('claims',[]))
                                    receipt=execute('weekly_materials',owner,['main_cloud_daily.py','--connect','--background','--allow-game-tasks','--task','echo','--weekly-rounds',str(remaining)],1500)
                                else:
                                    receipt=execute('garden',owner,['main_cloud_daily.py','--connect','--background','--allow-game-tasks','--task','garden'],2100)
                                weekly.finish(week_key(),name,owner,receipt)
                            except BaseException as exc:
                                weekly.fail(week_key(),name,owner,str(exc));raise
                        return weekly.read()[week_key()][name]
                    finally:
                        status['stages']['weekly_'+name]=weekly.read().get(week_key(),{}).get(name,{})
                        save()
                return action
            def echo_action(stage):
                def action():
                    try:
                        owner=uuid.uuid4().hex
                        if full.begin(day,stage,owner,time.time()):
                            try:
                                receipt=execute(stage,owner,['main_cloud_full_echo.py','--stage',stage],5520 if stage=='nest_echo' else 2700)
                                full.finish(day,stage,owner,receipt)
                            except BaseException as exc:
                                full.fail(day,stage,owner,str(exc),retry_allowed=False);raise
                        return full.read()[day][stage]
                    finally:
                        status['stages'][stage]=full.read().get(day,{}).get(stage,{})
                        save()
                return action
            def save_results(results):
                status['stage_results']=dict(results);save()
            plan=[('daily',True,daily_action),('weekly_boss',True,weekly_action('boss')),
                  ('weekly_garden',True,weekly_action('garden')),
                  ('boss_echo',False,echo_action('boss_echo')),('nest_echo',False,echo_action('nest_echo'))]
            summary=run_plan(plan,boundary,save_results)
            status.update(summary,current=None,completed_at=time.time())
            save();write_json(OUT/'result.json',status)
        except BaseException as e:
            status.update(status='FAILED',error=str(e),failed_at=time.time());save();write_json(OUT/'failure.json',status);raise
        finally:
            session.close()
        return 0 if status.get('required_complete') else 1

if __name__=='__main__':
    if '--scheduled' in sys.argv:
        OUT=Path('/opt/cloudgames/full-runs')/day_key()
        OUT.parent.mkdir(exist_ok=True)
    if '--preflight' in sys.argv:
        # Exercise the real identity, imports, locks and atomic output path.
        # No browser is opened and no resource/reward ledger is changed.
        OUT.mkdir(exist_ok=True)
        with sequence_guard(), ProcessLock(STATE/'runner.lock'):
            check_controls(STATE, child_active=False)
            test=OUT/('.preflight-'+uuid.uuid4().hex+'.json')
            write_json(test,{'preflight':True,'day':day_key()})
            assert json.loads(test.read_text())['preflight'] is True
            test.unlink()
            assert (Path('/opt/cloudgames/full-alignment-20261023')/'weekly-reference.json').is_file()
        print(json.dumps({'preflight':'passed','uid':os.getuid(),'output':str(OUT),'game_inputs':False}))
    else:
        sys.exit(main())
