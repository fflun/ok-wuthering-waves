from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from cloud_autorun_state import DailyLedger,write_json
from cloud_daily_retry import run_daily,DailyStageFailure
from cloud_daily_guard import activity_value,claimed_tick_scores,install
from cloud_weekly_chain import run_chain,execute_stage,WeeklyChainError
from cloud_weekly_state import WeeklyLedger

NOW=datetime(2026,10,6,12,tzinfo=timezone(timedelta(hours=8)))
DAY='2026-10-06'


class DailyRetryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.base=Path(self.folder.name);self.daily=DailyLedger(self.base/'daily.json')
    def test_one_failed_attempt_then_success_keeps_history_and_no_third(self):
        calls=[]
        def execute(owner):
            calls.append(owner)
            if len(calls)==1:raise DailyStageFailure('temporary stream failure',True)
            return dict(status='SUCCEEDED',run_id=owner)
        run_daily(self.daily,DAY,execute,lambda:None,retries=1)
        item=self.daily.read()[DAY]
        self.assertEqual(item['attempt_count'],2);self.assertEqual(item['status'],'SUCCEEDED')
        self.assertEqual(item['attempts'][0]['status'],'FAILED');self.assertEqual(len(set(calls)),2)
        with self.assertRaises(DailyStageFailure):run_daily(self.daily,DAY,execute,lambda:None,retries=1)
        self.assertEqual(len(calls),2)
    def test_two_failures_stop_weekly_and_notify_once(self):
        weekly=WeeklyLedger(self.base/'weekly.json');calls=[];notices=[]
        def execute(stage,*args):calls.append(stage);raise DailyStageFailure('failed',True)
        with self.assertRaises(WeeklyChainError):
            run_chain(self.daily,weekly,execute,lambda *args:notices.append(args),lambda:NOW,daily_retries=1)
        self.assertEqual(calls,['daily','daily']);self.assertEqual(len(notices),1)
        self.assertFalse(weekly.path.exists());self.assertFalse(self.daily.retryable(DAY))
        with self.assertRaises(WeeklyChainError):
            run_chain(self.daily,weekly,execute,now=lambda:NOW,daily_retries=1)
        self.assertEqual(calls,['daily','daily'])
    def test_pending_claim_stops_before_restart(self):
        checks=[True,False]
        def check():
            if not checks.pop(0):raise RuntimeError('pending claim')
        execute=Mock(side_effect=DailyStageFailure('claim uncertain',True))
        with self.assertRaises(DailyStageFailure):run_daily(self.daily,DAY,execute,lambda:None,1,check)
        execute.assert_called_once();self.assertFalse(self.daily.retryable(DAY))
    def test_stop_refresh_unowned_receipt_never_retry(self):
        for kind in ('stop','refresh','receipt'):
            with self.subTest(kind=kind):
                ledger=DailyLedger(self.base/(kind+'.json'));calls=[];checks=[0]
                def boundary():
                    checks[0]+=1
                    if kind=='refresh' and checks[0]>1:raise RuntimeError('refresh')
                def execute(owner):
                    calls.append(owner)
                    if kind=='stop':raise DailyStageFailure('stopped',False)
                    return dict(status='SUCCEEDED',run_id='other' if kind=='receipt' else owner)
                with self.assertRaises(RuntimeError):run_daily(ledger,DAY,execute,boundary,1)
                self.assertEqual(len(calls),1);self.assertFalse(ledger.retryable(DAY))
    def test_restarting_parent_resumes_only_one_recorded_safe_failure(self):
        self.daily.begin(DAY);self.daily.finish(DAY,'FAILED','safe failure',retry_allowed=True)
        execute=Mock(side_effect=lambda owner:dict(status='SUCCEEDED',run_id=owner))
        run_daily(self.daily,DAY,execute,lambda:None,1)
        execute.assert_called_once();self.assertEqual(self.daily.read()[DAY]['attempt_count'],2)
    def test_legacy_failed_and_interrupted_records_are_preserved(self):
        for status in ('FAILED','RUNNING'):
            write_json(self.daily.path,{DAY:dict(status=status)})
            execute=Mock()
            with self.assertRaises(DailyStageFailure):run_daily(self.daily,DAY,execute,lambda:None,1)
            execute.assert_not_called()
    def test_native_failure_receipt_controls_retry_and_sets_resume_flag(self):
        import time
        state=self.base/'session/background';state.mkdir(parents=True)
        root=self.base/'work/code';root.mkdir(parents=True)
        config=dict(python='fixture',browser_deps='fixture',runtime='fixture')
        DailyLedger(state/'daily-ledger.json').begin(DAY)
        ledger=DailyLedger(state/'daily-ledger.json');ledger.finish(DAY,'FAILED',retry_allowed=True)
        ledger.begin(DAY,retry_failed=True)
        def child(command,**kwargs):
            self.assertEqual(kwargs['env']['OKWW_DAILY_RETRY'],'1')
            write_json(state/'daily-result.json',dict(status='FAILED',run_id='owner',at=time.time()+1,retry_allowed=True))
            return Mock(returncode=1)
        with patch('subprocess.Popen',side_effect=child),patch('cloud_weekly_chain.day_key',return_value=DAY):
            with self.assertRaises(DailyStageFailure) as caught:
                execute_stage('daily','2026-10-05','owner',0,1500,config,root,state)
        self.assertTrue(caught.exception.retry_allowed)
    def test_success_without_completion_evidence_is_not_accepted_or_retried(self):
        import time
        state=self.base/'session/background';state.mkdir(parents=True)
        root=self.base/'work/code';root.mkdir(parents=True)
        config=dict(python='fixture',browser_deps='fixture',runtime='fixture')
        def child(command,**kwargs):
            write_json(state/'daily-result.json',dict(status='SUCCEEDED',run_id='owner',completed_at=time.time()+1))
            return Mock(returncode=0)
        with patch('subprocess.Popen',side_effect=child):
            with self.assertRaisesRegex(DailyStageFailure,'completion lacks') as caught:
                execute_stage('daily','2026-10-05','owner',0,1500,config,root,state)
        self.assertFalse(caught.exception.retry_allowed)
    def test_daily_recovers_then_weekly_runs_once(self):
        weekly=WeeklyLedger(self.base/'weekly.json');stages=[]
        def execute(stage,week,owner,remaining,timeout):
            stages.append(stage)
            if stages==['daily']:raise DailyStageFailure('temporary',True)
            if stage=='boss':
                for i in range(3):weekly.claim(week,owner,dict(status='CLAIM_VERIFIED',cost=60,
                    claim_id=str(i),verified_at=NOW.timestamp()+.5))
            return dict(status='SUCCEEDED',run_id=owner,game_week=week,completed_at=NOW.timestamp()+1,
                        current=6000,target=6000,verified_rewards=6)
        result=run_chain(self.daily,weekly,execute,now=lambda:NOW,daily_retries=1)
        self.assertEqual(stages,['daily','daily','boss','garden'])
        self.assertEqual(result['completed_stages'],['daily','boss','garden'])


class DailyGuardTests(unittest.TestCase):
    def test_completed_stamina_requires_positive_counter_after_scrollbar_drag(self):
        import numpy as np
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            task=Mock();task.frame=np.zeros((720,1280,3),dtype=np.uint8)
            task.frame[150:290,1246:1251]=230
            task.open_daily.return_value=(0,False)
            def ocr(*args,**kwargs):
                if args[0]==0:return ['活跃行迹']
                if 'match' not in kwargs:return ['90']
                return [SimpleNamespace(name='180/180')] if task.swipe_relative.called else []
            task.ocr.side_effect=ocr
            with patch('cloud_daily_guard.claimed_tick_scores',return_value=[.95]*4+[0]):
                install(task,folder,probe=True)
                self.assertEqual(task.open_daily(),(180,False))
            task.swipe_relative.assert_called_once()
            task.scroll_relative.assert_not_called()
            self.assertEqual(len(list(Path(folder).glob('*-stamina-list.png'))),1)
    def test_points_require_daily_page_and_single_value(self):
        self.assertEqual(activity_value(['活跃行迹'],['120']),120)
        for title,points in [(['主菜单'],['120']),(['活跃行迹'],[]),(['活跃行迹'],['20','100'])]:
            with self.assertRaises(RuntimeError):activity_value(title,points)
    def test_known_claimed_frame_and_missing_marker(self):
        import cv2
        root=Path(__file__).resolve().parents[3]
        path=Path('/opt/cloudgames/wuwa-20261023/okww-cloud-session/background/daily-evidence/1792691759322083882-daily-verification.png')
        frame=cv2.imread(str(path));self.assertIsNotNone(frame)
        self.assertTrue(all(score>.90 for score in claimed_tick_scores(frame)))
        frame[622:656,1163:1199]=0
        self.assertLess(claimed_tick_scores(frame)[-1],.90)
    def test_probe_never_calls_native_farming_or_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            import numpy as np
            task=Mock();task.frame=np.zeros((720,1280,3),dtype=np.uint8)
            task.ocr.side_effect=lambda *a,**kw:['活跃行迹'] if a[0]==0 else ['120']
            native_run,native_claim=task.run,task.claim_daily
            with patch('cloud_daily_guard.claimed_tick_scores',return_value=[.95]*5):
                install(task,folder,probe=True);task.run()
            native_run.assert_not_called();native_claim.assert_not_called()
            self.assertTrue(task._cloud_daily_verification['complete'])
            point_calls=[c for c in task.ocr.call_args_list if c.args[0]==.19]
            self.assertEqual(len(point_calls),4)
            scaled=[call for call in point_calls if 'frame_processor' in call.kwargs]
            self.assertEqual(len(scaled),2)
            for call in scaled:
                crop=np.zeros((72,141,3),dtype=np.uint8)
                self.assertEqual(call.kwargs['frame_processor'](crop).shape,(216,423,3))
    def test_retry_collects_earned_points_before_native_run_and_no_farming_on_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            import numpy as np
            task=Mock();task.frame=np.zeros((720,1280,3),dtype=np.uint8)
            task.is_browser.return_value=False
            task.open_daily.return_value=(0,False);events=[]
            task.ocr.side_effect=lambda *a,**kw:['活跃行迹'] if a[0]==0 else ['120']
            task.claim_daily.side_effect=lambda:events.append('claim')
            task.run.side_effect=lambda:events.append('native')
            closure=dict(game_day=DAY,complete=True,steps={s:dict(status='VERIFIED') for s in ('mail','radio_tasks','radio_rewards')})
            with patch('cloud_daily_guard.claimed_tick_scores',return_value=[.95]*5),patch('cloud_daily_closure.install',return_value=(closure,Mock())),patch('cloud_daily_guard.day_key',return_value=DAY):
                install(task,folder,resume=True);task.run()
                self.assertEqual(events,['claim','native']);self.assertEqual(task.open_daily(),(0,True))
                task.ocr.side_effect=lambda *a,**kw:['活跃行迹'] if a[0]==0 else ([] if 'match' in kw else ['20'])
                with self.assertRaisesRegex(RuntimeError,'stamina progress'):task.open_daily()


if __name__=='__main__':unittest.main()
