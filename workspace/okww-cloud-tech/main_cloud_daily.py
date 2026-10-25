"""Opt-in browser transport for upstream tasks; default invocation is offline."""
import argparse
import importlib
import json
import os
from pathlib import Path
import threading
import time


def task_time_limit(args, *, boss_batch=False):
    if boss_batch:
        if (args.account != 'a' or args.task != 'echo' or args.once_daily
                or args.forgery_rounds or args.weekly_probe or args.weekly_rounds):
            raise ValueError('Boss batch time limit requires the dedicated A echo queue')
        return 3000
    full_echo = os.environ.get('OKWW_FULL_RUN_ID') and args.task in ('echo', 'nightmare')
    return 2700 if full_echo else (1800 if args.task == 'garden' else 1200)


def verify_task_team(active, task_name, state, account):
    """Garden uses its own minigame controls and has no combat character loader."""
    if task_name == 'garden':
        return
    active.load_chars()
    observed_team = [type(c).__name__ for c in active.chars if c]
    if len(observed_team) != 3 or 'BaseChar' in observed_team:
        raise RuntimeError('Small-account team not recognized; no farming started')
    from cloud_autorun_state import write_json
    write_json(state / 'team-observation.json', {'account': account, 'team': observed_team})


def prepare_daily_team(active, pending_path):
    """After identity verification, check all three living slots before loading avatars."""
    from cloud_daily_policy import PendingClaim
    from cloud_revive import recovery_navigation, world_heal_and_reenter
    PendingClaim(pending_path).assert_clear()
    with recovery_navigation(active):
        active.ensure_main(time_out=60)
        world_heal_and_reenter(active, reenter=False)
    PendingClaim(pending_path).assert_clear()


def prepare_nest_team(active, pending_path):
    """Identity UI must return to two fresh world frames before avatar loading."""
    from cloud_daily_policy import PendingClaim
    PendingClaim(pending_path).assert_clear()
    active.ensure_main(time_out=60)
    active.next_frame()
    if not active.in_team_and_world():
        raise RuntimeError('Nest team preflight did not return to the world')
    active.sleep(.3)
    active.next_frame()
    if not active.in_team_and_world():
        raise RuntimeError('Nest team preflight world changed before character loading')
    PendingClaim(pending_path).assert_clear()


def main(argv=None, *, boss_batch=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account',choices=('a','b','c'),default='a')
    parser.add_argument('--bind-account',action='store_true')
    parser.add_argument('--connect', action='store_true', help='Start only the local browser bridge')
    parser.add_argument('--allow-game-tasks', action='store_true', help='Enable explicit daily/tacet/forgery commands')
    parser.add_argument('--background',action='store_true',help='Use the owned headless Chrome game profile')
    parser.add_argument('--once-daily',action='store_true',help='Run the original daily once and report its completion event')
    parser.add_argument('--daily-probe',action='store_true',help='Read daily activity/reward markers only; no farming or claims')
    parser.add_argument('--task',choices=('nightmare','echo','tacet','forgery','simulation','garden'),
                        help='Explicit on-demand original task; never scheduled with daily')
    parser.add_argument('--forgery-rounds',type=int,choices=(1,2,3),help='Bounded original ForgeryTask trial with 80 stamina per verified claim')
    parser.add_argument('--forgery-index',type=int,choices=range(1,21),help='Verified material domain index for this trial only')
    parser.add_argument('--weekly-probe',action='store_true',help='Inspect weekly reward UI without claiming')
    parser.add_argument('--nest-current',action='store_true',help='Resume one named nest, verify live identity and preserve pending pickup')
    parser.add_argument('--nest-unfinished',action='store_true',help='Explicit permission to select one visible unfinished nest')
    parser.add_argument('--weekly-rounds',type=int,choices=(1,2,3),help='Explicit first weekly boss 90-level material claims')
    parser.add_argument('--garden-probe',action='store_true',help='Inspect weekly garden page without entering a game')
    args = parser.parse_args(argv)
    if args.account!='a' and (not args.once_daily or args.task or args.forgery_rounds or not args.background):
        parser.error('B/C support only explicit background daily or daily-probe')
    if args.daily_probe and not args.once_daily:parser.error('Daily probe requires --once-daily')
    if args.garden_probe and args.task!='garden':parser.error('Garden probe requires --task garden')
    if args.nest_current and args.task != 'nightmare':parser.error('Current nest requires --task nightmare')
    if args.nest_unfinished and not args.nest_current:parser.error('Unfinished selection requires --nest-current')
    if (args.weekly_probe or args.weekly_rounds) and args.task != 'echo':
        parser.error('Weekly probe requires --task echo')
    if args.weekly_probe and args.weekly_rounds:parser.error('Choose probe or claims')
    if (args.once_daily or args.forgery_rounds or args.task) and not (args.connect and args.background and args.allow_game_tasks):
        parser.error('Bounded runs require --connect --background --allow-game-tasks')
    if args.forgery_rounds and (args.once_daily or not args.forgery_index):
        parser.error('Forgery trial requires an explicit index and cannot run alongside daily')
    if args.task and (args.once_daily or args.forgery_rounds):
        parser.error('Choose one task per run')
    if not args.connect:
        print('CLOUD_OFFLINE: no browser bridge or game task started.')
        return

    root = Path(__file__).resolve().parent
    session = root.parent / 'okww-cloud-session'
    state=session/'background'
    account_paths=account_settings=None
    if args.account!='a':
        from cloud_account_runtime import resolve_context
        account_paths,account_settings=resolve_context(root,args.account)
        session=account_paths.root
        state=account_paths.state
        state.mkdir(parents=True,exist_ok=True)
        account_paths.runtime_config.mkdir(parents=True,exist_ok=True)
        os.chdir(session)
        from ok import Config
        Config.config_folder=str(account_paths.runtime_config)

    from cloud_browser import CLOUD_WUWA_URL
    from cloud_daily_runtime import CloudCapture, CloudInteraction
    if args.background:
        from cloud_background_runtime import BackgroundCapture
        CloudCapture=BackgroundCapture
    from cloud_adapter import install
    from config import config
    from ok import OK
    from src.task.DailyTask import DailyTask
    from src.task.TacetTask import TacetTask
    from src.task.ForgeryTask import ForgeryTask
    from src.task.NightmareNestTask import NightmareNestTask
    from src.task.FarmEchoTask import FarmEchoTask
    from src.task.SimulationTask import SimulationTask
    from src.task.GardenTask import GardenTask

    runtime = Path(os.environ['OKWW_INSTALLED_RUNTIME'])
    session.mkdir(exist_ok=True)
    os.chdir(session)
    cfg = dict(config)
    for key in ('windows', 'gui', 'update_pyappify'):
        cfg.pop(key, None)
    cfg.update(use_gui=False, check_mutex=False, debug=False,
               config_folder=str(account_paths.runtime_config if account_paths else session/'daily-config'),
               log_file=str((account_paths.logs if account_paths else session/'daily-logs')/'runtime.log'),
               error_log_file=str((account_paths.logs if account_paths else session/'daily-logs')/'error.log'),
               screenshots_folder=str(account_paths.root/'screenshots' if account_paths else session/'daily-screenshots'))
    cfg['browser'] = dict(url=CLOUD_WUWA_URL, resolution=(1280,720),
                          nick='Cloud Wuwa (existing Chrome)',account_id=args.account)
    cfg['template_matching'] = dict(config['template_matching'],
        default_threshold=0.70,
        coco_feature_json=str(runtime/'assets'/'coco_annotations.json'))
    cfg['echo_model_path']=str(runtime/'assets'/'echo_model'/'echo.onnx')
    for name in ('ok.device.DeviceManager','ok.device.capture','ok.core.start_controller'):
        module = importlib.import_module(name)
        module.BrowserCaptureMethod = CloudCapture
        if hasattr(module,'BrowserInteraction'):
            module.BrowserInteraction = CloudInteraction
    pending_path = account_paths.pending_claim if account_paths else session / 'claim-pending.json'
    install(pending_path)
    app = OK(cfg)
    capture = interaction = None
    active = None
    deadline = 0
    shutting_down = threading.Event()
    completed=threading.Event()
    original_forgery_index=None
    result_path=None
    stop_reason=[None]

    def on_task_done(task):
        if task is active:
            completed.set()

    from ok.core.events import communicate
    communicate.task_done.connect(on_task_done)

    def stop():
        if capture is not None:
            capture.block_input = True
        for task in app.task_executor.onetime_tasks:
            if task.enabled:
                task.disable()
        if interaction is not None:
            interaction.release_all()

    def watchdog():
        was_running = False
        last_snapshot = 0
        while not shutting_down.wait(1):
            running = bool(active and active.enabled)
            try:
                if account_paths and capture is not None and time.monotonic()-last_snapshot>2:
                    import cv2
                    frame=capture.do_get_frame()
                    if frame is not None:
                        monitor=Path(os.environ.get('OKWW_DAILY_OUTPUT',str(state/'daily-evidence')))
                        monitor.mkdir(parents=True,exist_ok=True)
                        tmp=monitor/'viewer-next.png'
                        if cv2.imwrite(str(tmp),frame):tmp.replace(monitor/'viewer.png')
                    last_snapshot=time.monotonic()
                if args.forgery_rounds and running and time.monotonic()-last_snapshot>15:
                    import cv2
                    frame=app.task_executor.nullable_frame()
                    if frame is not None:
                        cv2.imwrite(str(state/'forgery-trial-current.png'),frame)
                    last_snapshot=time.monotonic()
                stop_request=state/'stop-request'
                if running and stop_request.exists():
                    stop_reason[0]='local_stop_request'
                    stop()
                    stop_request.unlink()
                    print('CLOUD_STOP local_stop_request',flush=True)
                elif running and time.monotonic() > deadline:
                    stop_reason[0]='time_limit'
                    stop()
                    print('CLOUD_STOP time_limit',flush=True)
                elif was_running and not running:
                    stop()
                    print('CLOUD_STOP task_finished_or_failed',flush=True)
            except Exception as exc:
                capture.block_input = True
                print('CLOUD_STOP cleanup_error '+str(exc),flush=True)
            was_running = running

    try:
        dm = app.device_manager
        dm.update_browser_device()
        dm.config['preferred'] = 'browser'
        dm.do_start()
        capture, interaction = dm.capture_method, dm.interaction
        # Avoid a second input owner in this dedicated cloud session.
        for task in app.task_executor.trigger_tasks:
            task.disable()
            task.enable_after_start = False
        # Actual upstream task classes: ForgeryTask retains DomainTask recovery.
        tasks = {'daily': app.get_onetime_task(DailyTask),
                 'tacet': app.get_onetime_task(TacetTask),
                 'forgery': app.get_onetime_task(ForgeryTask),
                 'nightmare':app.get_onetime_task(NightmareNestTask),
                 'echo':app.get_onetime_task(FarmEchoTask),
                 'simulation':app.get_onetime_task(SimulationTask),
                 'garden':app.get_onetime_task(GardenTask)}
        threading.Thread(target=watchdog,daemon=True).start()
        if args.once_daily or args.forgery_rounds or args.task:
            from cloud_daily_policy import PendingClaim, ForgeryClaimBudget
            PendingClaim(pending_path).assert_clear()
            # Daily may call these native domain tasks as children. Use the
            # same solvent-only entry policy when current stamina is below 40.
            for name in ('forgery','simulation','tacet'):
                tasks[name]._cloud_allow_solvent_entry = True
            if account_settings:
                from cloud_account_runtime import configure_daily
                configure_daily(tasks,account_settings)
            active=tasks[args.task or ('forgery' if args.forgery_rounds else 'daily')]
            if args.once_daily:
                from cloud_daily_guard import install as install_daily_guard
                install_daily_guard(active,Path(os.environ.get('OKWW_DAILY_OUTPUT',str(state/'daily-evidence'))),
                    probe=args.daily_probe,resume=os.environ.get('OKWW_DAILY_RETRY')=='1',
                    pending_claim=pending_path)
            if args.task=='garden':
                from cloud_garden_guard import install as install_garden
                install_garden(active,Path(os.environ.get('OKWW_GARDEN_OUTPUT',str(root.parent.parent/'outputs/garden-current'))),probe=args.garden_probe)
            if args.task == 'nightmare':
                from cloud_nightmare_observe import install as observe_nightmare
                observe_nightmare(active,capture,root.parent.parent/'outputs')
                if args.nest_current:
                    from cloud_nest_current import install as current_nest
                    if args.nest_unfinished:
                        current_nest(active,root.parent.parent/'outputs',allow_unfinished=True)
                    else:
                        current_nest(active,root.parent.parent/'outputs')
            if args.weekly_probe or args.weekly_rounds:
                from cloud_weekly_trial import install_probe
                install_probe(active,Path(os.environ.get('OKWW_WEEKLY_OUTPUT',str(root.parent.parent/'outputs'))),args.weekly_rounds or 0)
            if args.forgery_rounds:
                original_forgery_index=active.config.get('Which Forgery Challenge to Farm',1)
                active.config['Which Forgery Challenge to Farm']=args.forgery_index
                active._cloud_forgery_budget=ForgeryClaimBudget(args.forgery_rounds)
            active.config['Exit After Task']=False
            active.exit_after_task=False
            time_limit=task_time_limit(args,boss_batch=boss_batch)
            deadline=time.monotonic()+time_limit
            if args.forgery_rounds or args.task or args.once_daily:
                # Allow the stream/game to finish its initial transition before
                # native menu handling begins; never dispatch keys into black frames.
                ready_deadline=time.monotonic()+90
                stable_since=None
                import hashlib
                ready_hashes=set()
                while time.monotonic()<ready_deadline:
                    observed=capture.do_get_frame()
                    if observed is not None and observed.mean()>2:
                        stable_since=stable_since or time.monotonic()
                        ready_hashes.add(hashlib.blake2b(observed.tobytes(),digest_size=8).digest())
                        if time.monotonic()-stable_since>=15 and len(ready_hashes)>=3:break
                    else:
                        stable_since=None
                        ready_hashes.clear()
                    time.sleep(.5)
                else:raise RuntimeError('Background video did not become continuously visible')
                print('CLOUD_FORGERY_STREAM_READY '+json.dumps(capture.run_in_loop(capture.metrics())),flush=True)
            if capture.do_get_frame() is None:
                raise RuntimeError('No fresh background game frame')
            if account_paths or os.environ.get('OKWW_RESTART_RECHECK')=='1':
                from cloud_nest_current import read_account
                from cloud_account_runtime import verify_or_bind
                verified_run=active.run
                def account_run():
                    # next_frame/sleep require the native task executor to run.
                    # Keep inputs blocked until the account is verified.
                    identity_deadline=time.monotonic()+60
                    while True:
                        try:
                            observed_uid=read_account(active)
                            break
                        except RuntimeError:
                            import cv2
                            monitor=Path(os.environ.get('OKWW_DAILY_OUTPUT',str(state/'daily-evidence')))
                            monitor.mkdir(parents=True,exist_ok=True)
                            cv2.imwrite(str(monitor/'identity-wait.png'),active.frame)
                            if time.monotonic()>=identity_deadline:raise
                            active.sleep(2)
                    if account_paths:
                        verify_or_bind(root,args.account,observed_uid,allow_bind=args.bind_account)
                    else:
                        from cloud_accounts import verify_account_identity
                        registry=json.loads((state/'accounts/registry.json').read_text(encoding='utf-8'))
                        verify_account_identity(registry,'a',observed_uid)
                    print('ACCOUNT_IDENTITY_VERIFIED '+(args.account or 'a'),flush=True)
                    capture.block_input=False
                    cancel_cap=getattr(active,'_cloud_cancel_radio_cap',None)
                    if callable(cancel_cap) and cancel_cap():
                        active.ensure_main(time_out=60)
                    if args.once_daily and not args.daily_probe and args.account=='a':
                        prepare_daily_team(active,pending_path)
                    if args.account=='a' and args.task=='nightmare':
                        prepare_nest_team(active,pending_path)
                    verify_task_team(active,args.task,state,args.account or 'a')
                    return verified_run()
                active.run=account_run
            else:
                capture.block_input=False
            result_name=args.task or ('forgery-trial' if args.forgery_rounds else 'daily')
            if args.daily_probe:result_name='daily-probe'
            result_path=state/f'{result_name}-result.json'
            result_path.parent.mkdir(exist_ok=True)
            result_path.write_text(json.dumps({'status':'RUNNING','started_at':time.time()}),encoding='utf-8')
            app.headless_app.start_controller.do_start(active)
            while not completed.wait(.5):
                if time.monotonic()>deadline:
                    raise RuntimeError(f'Task exceeded {time_limit//60} minute limit')
                if not active.enabled and not active.running:
                    # task_done is emitted immediately after disabling on success.
                    if completed.wait(1):break
                    raise RuntimeError('Task stopped without a successful completion event')
            stop()
            PendingClaim(pending_path).assert_clear()
            if args.forgery_rounds and active._cloud_forgery_budget.completed != args.forgery_rounds:
                raise RuntimeError('Native task returned before all authorized claims completed')
            if args.weekly_rounds and active.info.get('Weekly Verified Claims')!=args.weekly_rounds:
                raise RuntimeError('Native weekly task returned before all requested claims completed')
            if args.once_daily and not args.daily_probe:
                from cloud_daily_closure import complete
                from cloud_autorun_state import day_key
                verification=getattr(active,'_cloud_daily_verification',{})
                if verification.get('all_daily_complete') is not True or not complete(verification.get('closure'),day_key()):
                    raise RuntimeError('Daily completion event lacks mandatory mail/radio evidence')
            import cv2
            frame=capture.do_get_frame()
            if frame is not None:
                cv2.imwrite(str(state/f'{result_name}-completed.png'),frame)
            result_path.write_text(json.dumps({'status':'SUCCEEDED','completed_at':time.time(),
                'source':'native TaskExecutor.task_done','task':type(active).__name__,'info':dict(active.info),
                'verified_claims':active._cloud_forgery_budget.completed if args.forgery_rounds else None,
                'run_id':os.environ.get('OKWW_RUN_ID'),
                'daily_verification':getattr(active,'_cloud_daily_verification',None),
                'game_week':os.environ.get('OKWW_WEEKLY_WEEK'),
                'verified_weekly_claims':active.info.get('Weekly Verified Claims') if args.weekly_rounds else None},
                ensure_ascii=False,indent=2),encoding='utf-8')
            print('CLOUD_DAILY_SUCCEEDED',flush=True)
            return
        print('CLOUD_READY: status / snapshot / daily / tacet / forgery / stop / quit; tasks opt-in only',flush=True)
        while True:
            try:
                command = input().strip().lower()
            except EOFError:
                break
            try:
                if command == 'status':
                    print('CLOUD_STATUS '+json.dumps(dict(video=capture.run_in_loop(capture.metrics()),
                        capture_ms=capture.last_capture_ms, task=type(active).__name__ if active else None,
                        enabled=bool(active and active.enabled), info=dict(active.info) if active else {})),flush=True)
                elif command == 'snapshot':
                    import cv2
                    frame = capture.do_get_frame()
                    if frame is None:
                        raise RuntimeError('No connected game video')
                    destination = session/'daily-screenshots'/'cloud-current.png'
                    destination.parent.mkdir(exist_ok=True)
                    if not cv2.imwrite(str(destination),frame):
                        raise RuntimeError('Could not save game screenshot')
                    print('CLOUD_SNAPSHOT '+str(destination),flush=True)
                elif command in tasks:
                    if not args.allow_game_tasks:
                        raise RuntimeError('Game tasks are disabled in this connection session')
                    from cloud_daily_policy import PendingClaim
                    PendingClaim(pending_path).assert_clear()
                    if app.task_executor.current_task or any(t.enabled for t in app.task_executor.onetime_tasks):
                        raise RuntimeError('A task is already running')
                    if capture.do_get_frame() is None:
                        raise RuntimeError('No connected game video')
                    active = tasks[command]
                    deadline = time.monotonic()+1200
                    capture.block_input = False
                    try:
                        print('CLOUD_START',app.headless_app.start_controller.do_start(active),flush=True)
                    except BaseException:
                        stop()
                        raise
                elif command == 'stop':
                    stop()
                    print('CLOUD_STOP requested',flush=True)
                elif command == 'quit':
                    break
                else:
                    raise ValueError('Unknown command; experimental trial/resume commands retired')
            except Exception as exc:
                print('CLOUD_ERROR '+str(exc),flush=True)
    except BaseException as exc:
        if result_path is not None:
            result_path.write_text(json.dumps({'status':'FAILED','error':str(exc),'at':time.time(),
                'run_id':os.environ.get('OKWW_RUN_ID'),
                'retry_allowed':stop_reason[0]!='local_stop_request' and not pending_path.exists() and not (state/'stop-request').exists(),
                'daily_verification':getattr(active,'_cloud_daily_verification',None),
                'daily_closure':getattr(active,'_cloud_daily_closure',None),
                'verified_claims':getattr(getattr(active,'_cloud_forgery_budget',None),'completed',None)},indent=2),encoding='utf-8')
        if (args.forgery_rounds or args.task) and capture is not None and capture.connected():
            try:
                import cv2
                stop()
                frame=capture.do_get_frame()
                cv2.imwrite(str(state/'forgery-trial-failed.png'),frame)
                print('CLOUD_FORGERY_FAILURE_METRICS '+json.dumps(capture.run_in_loop(capture.metrics())),flush=True)
                capture.run_in_loop(capture.driver.page.screenshot(path=str(state/'forgery-trial-failed-page.png')))
            except Exception as diagnostic_error:
                print('CLOUD_DIAGNOSTIC_ERROR '+str(diagnostic_error),flush=True)
        raise
    finally:
        shutting_down.set()
        if original_forgery_index is not None:
            active.config['Which Forgery Challenge to Farm']=original_forgery_index
        communicate.task_done.disconnect(on_task_done)
        try:
            stop()
        finally:
            app.exit_event.set()
            if app.task_executor.thread:
                app.task_executor.thread.join(timeout=5)
            if capture is not None:
                capture.close()


if __name__ == '__main__':
    main()
