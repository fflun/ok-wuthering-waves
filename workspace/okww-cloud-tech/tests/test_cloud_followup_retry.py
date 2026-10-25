from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from cloud_autorun_state import DailyLedger,write_json
from cloud_daily_retry import DailyStageFailure
from cloud_echo_progress import EchoProgress,verified_boss_progress
from cloud_full_chain import FullLedger,run_full_chain
from cloud_weekly_state import WeeklyLedger
from cloud_weekly_chain import run_chain,WeeklyChainError
import cloud_failure_notice as notice
from cloud_toast_notice import content

NOW=datetime(2026,10,6,12,tzinfo=timezone(timedelta(hours=8)));DAY='2026-10-06';WEEK='2026-10-05'


class FollowupRetryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.base=Path(folder.name);self.daily=DailyLedger(self.base/'daily.json')
        self.weekly=WeeklyLedger(self.base/'weekly.json');self.full=FullLedger(self.base/'full.json')
        write_json(self.daily.path,{DAY:{'status':'SUCCEEDED'}})
        write_json(self.weekly.path,{WEEK:{'boss':{'status':'SUCCEEDED'},'garden':{'status':'SUCCEEDED'}}})
    def receipt(self,stage,day,owner):
        return dict(status='SUCCEEDED',run_id=owner,game_day=day,completed_at=NOW.timestamp()+1,
                    combats_completed=20,catalog_complete=True)
    def test_boss_retries_once_then_nests_and_completed_daily_not_repeated(self):
        calls=[];retries=[];recovered=[];terminal=[]
        def echo(stage,day,owner,timeout):
            calls.append(stage)
            if len(calls)==1:raise DailyStageFailure('temporary',True)
            return self.receipt(stage,day,owner)
        result=run_full_chain(self.daily,self.weekly,self.full,Mock(side_effect=AssertionError('base repeats')),echo,
            now=lambda:NOW,stage_retries=1,on_retry=lambda s,e:retries.append(s),
            on_recovered=lambda s:recovered.append(s),notify=lambda s,e:terminal.append(s))
        self.assertEqual(calls,['boss_echo','boss_echo','nest_echo'])
        self.assertEqual(retries,['boss_echo']);self.assertEqual(recovered,['boss_echo']);self.assertEqual(terminal,[])
        self.assertEqual(result['completed_stages'],['boss_echo','nest_echo'])
        self.assertEqual(self.full.read()[DAY]['boss_echo']['attempt_count'],2)
    def test_two_failures_stop_and_terminal_notice_once(self):
        calls=[];notices=[]
        def echo(stage,*a):calls.append(stage);raise DailyStageFailure('stalled',True)
        with self.assertRaises(WeeklyChainError):
            run_full_chain(self.daily,self.weekly,self.full,Mock(),echo,now=lambda:NOW,stage_retries=1,
                           notify=lambda s,e:notices.append(s))
        self.assertEqual(calls,['boss_echo','boss_echo']);self.assertEqual(notices,['boss_echo'])
        self.assertFalse(self.full.retryable(DAY,'boss_echo'))
        self.assertNotIn('nest_echo',self.full.read()[DAY])
    def test_nest_retries_without_refarming_twenty_bosses(self):
        calls=[]
        def echo(stage,day,owner,timeout):
            calls.append(stage)
            if calls==['boss_echo','nest_echo']:raise DailyStageFailure('pending pickup',True)
            return self.receipt(stage,day,owner)
        run_full_chain(self.daily,self.weekly,self.full,Mock(),echo,now=lambda:NOW,stage_retries=1)
        self.assertEqual(calls,['boss_echo','nest_echo','nest_echo'])
    def test_pending_spend_or_user_stop_forbids_restart(self):
        calls=[];checks=[0]
        def check():
            checks[0]+=1
            if checks[0]>1:raise RuntimeError('pending claim')
        def echo(stage,*a):calls.append(stage);raise DailyStageFailure('failed',True)
        with self.assertRaises(WeeklyChainError):
            run_full_chain(self.daily,self.weekly,self.full,Mock(),echo,now=lambda:NOW,stage_retries=1,retry_check=check)
        self.assertEqual(calls,['boss_echo']);self.assertFalse(self.full.retryable(DAY,'boss_echo'))
    def test_weekly_partial_claims_retry_only_remaining_two(self):
        self.weekly.path.unlink();calls=[];counter=[0]
        def execute(stage,week,owner,remaining,timeout):
            calls.append((stage,remaining))
            if stage=='boss':
                for i in range(1 if len(calls)==1 else remaining):
                    counter[0]+=1
                    self.weekly.claim(week,owner,dict(status='CLAIM_VERIFIED',cost=60,claim_id=str(counter[0]),verified_at=NOW.timestamp()+.5))
                if len(calls)==1:raise DailyStageFailure('after first verified claim',True)
            return dict(status='SUCCEEDED',run_id=owner,game_week=week,completed_at=NOW.timestamp()+1,current=6000,target=6000,verified_rewards=6)
        run_chain(self.daily,self.weekly,execute,now=lambda:NOW,stage_retries=1)
        self.assertEqual(calls,[('boss',3),('boss',2),('garden',0)])
        self.assertEqual(len(self.weekly.read()[WEEK]['boss']['claims']),3)
    def test_three_verified_claims_finish_without_fourth_game_claim(self):
        self.weekly.path.unlink();self.weekly.begin(WEEK,'boss','old',NOW.timestamp())
        for i in range(3):self.weekly.claim(WEEK,'old',dict(status='CLAIM_VERIFIED',cost=60,claim_id=str(i),verified_at=NOW.timestamp()+.5))
        self.weekly.fail(WEEK,'boss','old','exit failed',retry_allowed=True)
        records=self.weekly.read();records[WEEK]['garden']={'status':'SUCCEEDED'};write_json(self.weekly.path,records)
        execute=Mock(side_effect=AssertionError('no fourth claim'))
        result=run_chain(self.daily,self.weekly,execute,now=lambda:NOW,stage_retries=1)
        execute.assert_not_called();self.assertEqual(result['completed_stages'],['boss'])
    def test_invalid_completion_is_not_retried(self):
        echo=Mock(side_effect=lambda s,d,r,t:dict(self.receipt(s,d,r),combats_completed=19))
        with self.assertRaises(WeeklyChainError):run_full_chain(self.daily,self.weekly,self.full,Mock(),echo,now=lambda:NOW,stage_retries=1)
        echo.assert_called_once();self.assertFalse(self.full.retryable(DAY,'boss_echo'))


class BossProgressTests(unittest.TestCase):
    def test_victory_waits_for_pickup_and_restart_preserves_rounds(self):
        with tempfile.TemporaryDirectory() as folder,patch('cloud_echo_progress.day_key',return_value=DAY):
            path=Path(folder)/'progress.json';progress=EchoProgress(path,'synthetic-account',DAY)
            progress.victory('one','victory.png')
            reopened=EchoProgress(path,'synthetic-account',DAY)
            self.assertEqual(reopened.completed,0);self.assertEqual(reopened.pending['round'],1)
            with self.assertRaises(RuntimeError):reopened.victory('two','victory.png')
            reopened.pickup_finished(True,'pickup.png')
            for i in range(2,21):
                reopened.victory('two',str(i)+'-victory.png');reopened.pickup_finished(i%2==0,str(i)+'-pickup.png')
            self.assertEqual(EchoProgress(path,'synthetic-account',DAY).completed,20)
            self.assertEqual(len(verified_boss_progress(path,DAY)['rounds']),20)
            with self.assertRaises(RuntimeError):reopened.victory('three','another.png')
            with self.assertRaises(RuntimeError):EchoProgress(path,'other-account',DAY)
            with self.assertRaises(RuntimeError):verified_boss_progress(path,'2026-10-07')
    def test_pending_victory_is_not_complete_or_lost_on_restart(self):
        with tempfile.TemporaryDirectory() as folder,patch('cloud_echo_progress.day_key',return_value=DAY):
            path=Path(folder)/'p.json';progress=EchoProgress(path,'synthetic-account',DAY)
            progress.victory('owner','image')
            with self.assertRaises(RuntimeError):verified_boss_progress(path,DAY)
            self.assertEqual(EchoProgress(path,'synthetic-account',DAY).pending['run_id'],'owner')


class RetainedNoticeTests(unittest.TestCase):
    def test_retry_and_terminal_have_persistent_file_and_history(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder);write_json(state/'notifications.json',dict(local_enabled=True,toast_enabled=True,enabled=False))
            with patch('cloud_toast_notice.show_toast_notice',return_value={'history_retained':True}) as toast:
                notice.notify_retry(state,'boss_echo','temporary')
                notice.notify_failure(state,'boss_echo','failed again')
            self.assertEqual(toast.call_count,2)
            events=[json.loads(line) for line in (state/'notice-history.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([e['event'] for e in events],['RETRYING','FAILED'])
            self.assertEqual(events[-1]['status'],'LOCAL_DISPATCHED')
            self.assertIn('目标 BOSS', (state/'后台失败通知.txt').read_text(encoding='utf-8'))
    def test_missing_retention_not_claimed_delivered(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder);write_json(state/'notifications.json',dict(local_enabled=True,toast_enabled=True,enabled=False))
            with patch('cloud_toast_notice.show_toast_notice',return_value={'history_retained':False}):notice.notify_failure(state,'garden','failed')
            record=json.loads((state/'failure-notice.json').read_text(encoding='utf-8'))
            self.assertEqual(record['status'],'NOT_DELIVERED');self.assertEqual(record['local_status'],'SEND_FAILED')
    def test_notification_content_has_stage_without_raw_errors(self):
        title,body=content('nest_echo','RETRYING')
        self.assertIn('残象聚落',title);self.assertIn('补做一次',body)


if __name__=='__main__':unittest.main()
