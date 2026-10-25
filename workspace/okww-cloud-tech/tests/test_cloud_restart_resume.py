from datetime import datetime, timezone, timedelta
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from cloud_autorun_state import DailyLedger,write_json
from cloud_restart_resume import reconcile,validate_checkpoint

NOW=datetime(2026,10,10,13,tzinfo=timezone(timedelta(hours=8)))
BOOT=NOW.timestamp()-600
UID='a'*64

class RestartTests(unittest.TestCase):
    def test_final_nest_unconfirmed_checkpoint_stays_terminal_and_rejects_scope_drift(self):
        import hashlib
        from cloud_nest_state import OPTIONAL_PICKUP_TARGET
        image=self.state/'proof.png';image.write_bytes(b'proof fixture')
        record=dict(account=UID,day='2026-10-10',target=OPTIONAL_PICKUP_TARGET,
            total=24,book_count=[24,24],verified_count=[24,24],phase='PICKUP_UNCONFIRMED_ALLOWED',absorbed=False,
            pickup_search=dict(target=OPTIONAL_PICKUP_TARGET,count=[24,24],absorb_sent=True,
                bounded_search_completed=True,user_policy='final_nest_ignore_unconfirmed_absorption',
                image=str(image),image_sha256=hashlib.sha256(image.read_bytes()).hexdigest()))
        path=self.state/'nest-state-last.json';write_json(path,record)
        self.assertIsNone(validate_checkpoint(self.state,UID,'2026-10-10','nest_echo')['pending_target'])
        record['target']='另一残象聚落';write_json(path,record)
        with self.assertRaisesRegex(RuntimeError,'final-nest'):validate_checkpoint(self.state,UID,'2026-10-10','nest_echo')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'work/code';self.root.mkdir(parents=True)
        self.state=self.root.parent/'session/background';self.state.mkdir(parents=True)
        write_json(self.state/'accounts/registry.json',{'accounts':[{'id':a,'expected_uid_hash':UID} for a in ('a','b','c')]})
        self.config={'small_accounts_after_full':['b','c']}
    def run_check(self,active=None):
        return reconcile(self.root,self.state,self.config,snapshot={'boot_at':BOOT,'active':active or []},now=NOW)
    def daily(self,status='RUNNING',day='2026-10-10',started=None):
        record={'status':status,'run_id':'owned','started_at':started or BOOT-120,'attempt_count':2,'attempts':[{'status':'FAILED'}]}
        write_json(self.state/'daily-ledger.json',{day:record});return record
    def test_preboot_daily_resumes_once_without_erasing_attempts(self):
        self.daily();audit=self.run_check()
        ledger=DailyLedger(self.state/'daily-ledger.json')
        self.assertEqual(audit[0]['checkpoint']['mode'],'live_daily_activity_stamina_mail_radio_recheck')
        self.assertEqual(ledger.read()['2026-10-10']['status'],'READY')
        self.assertTrue(ledger.begin('2026-10-10')[0]);ledger.own('2026-10-10','new')
        self.assertEqual(ledger.read()['2026-10-10']['attempt_count'],3)
        self.assertEqual(len(ledger.read()['2026-10-10']['attempts']),3)
        with self.assertRaisesRegex(RuntimeError,'not a reboot'):self.run_check()
    def test_completed_daily_and_failed_daily_are_never_reset(self):
        for status in ('SUCCEEDED','FAILED'):
            record=self.daily(status);self.assertEqual(self.run_check(),[])
            self.assertEqual(DailyLedger(self.state/'daily-ledger.json').read()['2026-10-10'],record)
    def test_same_boot_interruption_and_live_child_block(self):
        self.daily(started=BOOT+1)
        with self.assertRaisesRegex(RuntimeError,'not a reboot'):self.run_check()
        with self.assertRaisesRegex(RuntimeError,'still active'):self.run_check([{'pid':123,'created_at':BOOT}])
    def test_cross_refresh_no_partial_reconciliation(self):
        self.daily(day='2026-10-09')
        with self.assertRaisesRegex(RuntimeError,'04:00'):self.run_check()
        self.assertEqual(DailyLedger(self.state/'daily-ledger.json').read()['2026-10-09']['status'],'RUNNING')
    def test_stop_and_pending_resource_block_before_write(self):
        self.daily()
        for path,value in [(self.state/'stop-request','1'),(self.state.parent/'claim-pending.json','{}'),
                           (self.state/'food-receipt.json','{"pending":{"use":1}}')]:
            path.write_text(value)
            with self.assertRaises(RuntimeError):self.run_check()
            path.unlink()
        self.assertEqual(DailyLedger(self.state/'daily-ledger.json').read()['2026-10-10']['status'],'RUNNING')
    def test_pending_nest_keeps_completion_and_same_target(self):
        write_json(self.state/'full-ledger.json',{'2026-10-10':{'nest_echo':{'status':'RUNNING','run_id':'nest',
            'started_at':BOOT-100,'attempt_count':1}}})
        nest={'account':UID,'day':'2026-10-10','target':'陷足流川残象聚落','phase':'CLEARED_PENDING_PICKUP',
              'total':24,'book_count':[24,24],'verified_count':[24,24]}
        write_json(self.state/'nest-state-test.json',nest)
        audit=self.run_check()
        self.assertEqual(audit[0]['checkpoint']['pending_target'],nest['target'])
        self.assertEqual(audit[0]['checkpoint']['pending_phase'],'CLEARED_PENDING_PICKUP')
        self.assertEqual(__import__('json').loads((self.state/'nest-state-test.json').read_text(encoding='utf-8')),nest)
    def test_bad_nest_counts_and_multiple_pending_block(self):
        nest={'account':UID,'day':'2026-10-10','target':'某残象聚落','phase':'CLEARED_PENDING_PICKUP',
              'total':24,'book_count':[24,24],'verified_count':[23,24]}
        write_json(self.state/'nest-state-test.json',nest)
        with self.assertRaisesRegex(RuntimeError,'completion evidence'):validate_checkpoint(self.state,UID,'2026-10-10','nest_echo')
        nest['verified_count']=[24,24]
        for name in ('one','two'):write_json(self.state/f'nest-state-{name}.json',nest)
        (self.state/'nest-state-test.json').unlink()
        with self.assertRaisesRegex(RuntimeError,'Multiple'):validate_checkpoint(self.state,UID,'2026-10-10','nest_echo')
    def test_owned_completion_is_restored_no_extra_execution(self):
        self.daily()
        receipt={'status':'SUCCEEDED','run_id':'owned','completed_at':BOOT-10,'daily_verification':{
            'game_day':'2026-10-10','complete':True,'activity':110,'verified_rewards':5,
            'all_daily_complete':True,'verified_at':BOOT-10,'closure':{'complete':True}}}
        write_json(self.state/'daily-result.json',receipt)
        with patch('cloud_daily_closure.complete',return_value=True):audit=self.run_check()
        self.assertEqual(audit[0]['action'],'owned_completion_restored')
        self.assertEqual(DailyLedger(self.state/'daily-ledger.json').read()['2026-10-10']['status'],'SUCCEEDED')
    def test_b_account_reconciles_only_its_own_daily(self):
        from cloud_accounts import account_paths
        state=account_paths(self.state,'b').state
        write_json(state/'daily-ledger.json',{'2026-10-10':{'status':'RUNNING','started_at':BOOT-10,'attempt_count':1}})
        audit=self.run_check();self.assertEqual(audit[0]['account'],'b')
        self.assertFalse((self.state/'daily-ledger.json').exists())
    def test_weekly_keeps_verified_claims(self):
        claims=[{'claim_id':'one','status':'CLAIM_VERIFIED','cost':60}]
        write_json(self.state/'weekly-ledger.json',{'2026-10-05':{'boss':{'status':'RUNNING','run_id':'w',
            'started_at':BOOT-1,'attempt_count':1,'claims':claims}}})
        self.run_check()
        from cloud_weekly_state import WeeklyLedger
        self.assertEqual(WeeklyLedger(self.state/'weekly-ledger.json').read()['2026-10-05']['boss']['claims'],claims)
