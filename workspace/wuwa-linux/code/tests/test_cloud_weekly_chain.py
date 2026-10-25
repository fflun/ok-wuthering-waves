from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cloud_autorun_state import DailyLedger,week_key,write_json
from cloud_weekly_state import WeeklyLedger,assert_expected_week
from cloud_weekly_chain import run_chain,plan_chain,assert_weekly_ready,WeeklyChainError

ZONE=timezone(timedelta(hours=8))
MON=datetime(2026,10,5,10,tzinfo=ZONE)


class WeeklyChainTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.base=Path(self.folder.name)
        self.daily=DailyLedger(self.base/'daily.json');self.weekly=WeeklyLedger(self.base/'weekly.json')
        self.calls=[];self.notices=[];self.now=MON
    def receipt(self,week,run_id,**extra):
        return dict(status='SUCCEEDED',run_id=run_id,game_week=week,
                    completed_at=self.now.timestamp()+1,**extra)
    def execute(self,stage,week,run_id,remaining,timeout):
        self.calls.append((stage,remaining,timeout))
        if stage=='boss':
            for i in range(remaining):
                self.weekly.claim(week,run_id,dict(status='CLAIM_VERIFIED',cost=60,
                    claim_id=run_id+':'+str(i),verified_at=self.now.timestamp()+.5,image='fixture'))
            return self.receipt(week,run_id)
        if stage=='garden':return self.receipt(week,run_id,current=6000,target=6000,verified_rewards=6)
        return self.receipt(week,run_id)
    def run_chain(self,execute=None):
        return run_chain(self.daily,self.weekly,execute or self.execute,
                         lambda stage,error:self.notices.append((stage,error)),lambda:self.now)
    def complete_daily(self):
        self.daily.begin('2026-10-05');self.daily.finish('2026-10-05','SUCCEEDED')
    def test_monday_four_boundary_and_tuesday_catchup(self):
        self.assertEqual(week_key(datetime(2026,10,5,3,59,59,tzinfo=ZONE)),'2026-09-28')
        self.assertEqual(week_key(datetime(2026,10,5,4,tzinfo=ZONE)),'2026-10-05')
        self.assertEqual(week_key(datetime(2026,10,6,12,tzinfo=ZONE)),'2026-10-05')
        self.assertEqual(week_key(datetime(2026,10,5,3,tzinfo=ZONE).astimezone(timezone.utc)),'2026-09-28')
    def test_order_and_no_duplicate_after_restart(self):
        result=self.run_chain()
        self.assertEqual(result['completed_stages'],['daily','boss','garden'])
        self.assertEqual([x[0] for x in self.calls],['daily','boss','garden'])
        self.calls.clear();self.assertEqual(self.run_chain()['status'],'SKIPPED');self.assertEqual(self.calls,[])
    def test_completed_daily_still_checks_weekly(self):
        self.complete_daily();self.run_chain()
        self.assertEqual([x[0] for x in self.calls],['boss','garden'])
    def test_new_day_runs_daily_but_skips_finished_weekly(self):
        self.run_chain();self.calls.clear();self.now=MON+timedelta(days=1);self.run_chain()
        self.assertEqual([x[0] for x in self.calls],['daily'])
    def test_new_week_has_new_quota(self):
        self.run_chain();self.calls.clear();self.now=MON+timedelta(days=7);self.run_chain()
        self.assertEqual([x[:2] for x in self.calls],[('daily',0),('boss',3),('garden',0)])
    def test_daily_failure_blocks_weekly_and_retry(self):
        def fail(*args):self.calls.append(('daily',));raise RuntimeError('daily failed')
        with self.assertRaises(WeeklyChainError):self.run_chain(fail)
        self.assertEqual(self.calls,[('daily',)])
        self.assertEqual(self.daily.read()['2026-10-05']['status'],'FAILED')
        self.assertFalse(self.weekly.path.exists())
        with self.assertRaises(WeeklyChainError):self.run_chain()
        self.assertEqual(len(self.calls),1)
    def test_boss_partial_claims_survive_failure_and_explicit_review(self):
        self.complete_daily()
        def fail(stage,week,run_id,remaining,timeout):
            self.calls.append((stage,remaining,timeout))
            self.weekly.claim(week,run_id,dict(status='CLAIM_VERIFIED',cost=60,
                claim_id=run_id+':1',verified_at=self.now.timestamp()+.5))
            raise RuntimeError('stalled after first reward')
        with self.assertRaises(WeeklyChainError):self.run_chain(fail)
        item=self.weekly.read()['2026-10-05']['boss']
        self.assertEqual(item['status'],'FAILED');self.assertEqual(len(item['claims']),1)
        self.assertEqual(self.run_chain()['status'],'NEEDS_ATTENTION')
        self.assertEqual(len(self.calls),1)
        self.weekly.authorize_resume_after_review('2026-10-05','boss')
        self.calls.clear();self.run_chain();self.assertEqual(self.calls[0][1],2)
        self.assertEqual(len(self.weekly.read()['2026-10-05']['boss']['claims']),3)
    def test_garden_bad_receipt_keeps_daily_and_boss_success(self):
        def execute(stage,*args):
            receipt=self.execute(stage,*args)
            if stage=='garden':receipt['verified_rewards']=5
            return receipt
        with self.assertRaises(WeeklyChainError):self.run_chain(execute)
        self.assertEqual(self.daily.read()['2026-10-05']['status'],'SUCCEEDED')
        stages=self.weekly.read()['2026-10-05']
        self.assertEqual(stages['boss']['status'],'SUCCEEDED')
        self.assertEqual(stages['garden']['status'],'FAILED')
        self.assertEqual(self.notices[-1][0],'garden')
        self.calls.clear();self.notices.clear();self.now=MON+timedelta(days=1)
        self.assertEqual(self.run_chain()['status'],'NEEDS_ATTENTION')
        self.assertEqual([x[0] for x in self.calls],['daily'])
        self.assertEqual(self.notices,[])
    def test_interrupted_old_week_blocks_new_week(self):
        self.weekly.begin('2026-09-28','boss','old')
        with self.assertRaises(WeeklyChainError):self.run_chain()
        self.assertEqual(self.calls,[])
    def test_refresh_after_daily_stops_before_weekly(self):
        self.now=datetime(2026,10,5,3,59,59,tzinfo=ZONE)
        def execute(stage,week,run_id,*args):
            self.calls.append((stage,));self.now+=timedelta(seconds=2)
            return self.receipt(week,run_id)
        with self.assertRaises(WeeklyChainError):self.run_chain(execute)
        self.assertEqual(self.calls,[('daily',)])
    def test_receipt_ownership_and_missing_claim_evidence(self):
        self.complete_daily()
        for fault in ('run_id','claims'):
            def bad(stage,week,run_id,remaining,timeout):
                return self.receipt(week,'other' if fault=='run_id' else run_id)
            with self.subTest(fault=fault),self.assertRaises(WeeklyChainError):self.run_chain(bad)
            self.weekly.path.unlink()
    def test_stale_completion_and_duplicate_or_fourth_claim(self):
        week='2026-10-05';run_id='owner';self.weekly.begin(week,'boss',run_id,MON.timestamp())
        evidence=dict(status='CLAIM_VERIFIED',cost=60,claim_id='a',verified_at=MON.timestamp()+1)
        self.weekly.claim(week,run_id,evidence)
        with self.assertRaises(RuntimeError):self.weekly.claim(week,run_id,evidence)
        for name in ('b','c'):self.weekly.claim(week,run_id,dict(evidence,claim_id=name))
        with self.assertRaises(RuntimeError):self.weekly.claim(week,run_id,dict(evidence,claim_id='d'))
        with self.assertRaises(RuntimeError):self.weekly.finish(week,'boss',run_id,
            self.receipt(week,run_id)|{'completed_at':MON.timestamp()-1})
    def test_disabled_or_unverified_chain_cannot_start(self):
        for config,acceptance in [({},{}),({'weekly_enabled':True},{}),
            ({'weekly_enabled':True},{'weekly_chain_live_verified':True})]:
            with self.assertRaises(RuntimeError):assert_weekly_ready(acceptance,config)
        assert_weekly_ready({'weekly_chain_live_verified':True},
                            {'weekly_enabled':True,'weekly_scheduler_timeout_seconds':5400})
    def test_readonly_plan_does_not_create_ledgers(self):
        with patch('subprocess.Popen',side_effect=AssertionError('browser forbidden')):
            plan=plan_chain(self.daily,self.weekly,MON)
        self.assertEqual(plan['week'],'2026-10-05')
        self.assertFalse(self.daily.path.exists());self.assertFalse(self.weekly.path.exists())
    def test_claim_guard_rejects_week_refresh(self):
        with patch.dict('os.environ',{'OKWW_WEEKLY_WEEK':'1900-01-01'}):
            with self.assertRaises(RuntimeError):assert_expected_week()
    def test_history_import_is_idempotent_and_rejects_incomplete_rewards(self):
        path=self.base/'garden-history.json'
        write_json(path,dict(status='SUCCEEDED',game_day='2026-10-05',current=6000,target=6000,verified_rewards=6))
        self.assertTrue(self.weekly.import_verified('garden',path))
        self.assertFalse(self.weekly.import_verified('garden',path))
        self.assertEqual(self.weekly.read()['2026-10-05']['garden']['status'],'SUCCEEDED')
        write_json(path,dict(status='SUCCEEDED',game_day='2026-10-12',current=6000,target=6000,verified_rewards=5))
        with self.assertRaises(RuntimeError):self.weekly.import_verified('garden',path)


if __name__=='__main__':unittest.main()
