import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cloud_small_account_chain import run_tail,small_account_order
from cloud_accounts import account_paths
from cloud_daily_retry import DailyStageFailure

DAY='2026-10-07'

class SmallChainTests(unittest.TestCase):
    def result(self):return dict(mode='full',status='SUCCEEDED',day=DAY)
    def test_order_isolation_and_no_duplicate_completed_daily(self):
        with tempfile.TemporaryDirectory() as d,patch('cloud_small_account_chain.day_key',return_value=DAY):
            state=Path(d);calls=[]
            def execute(a,owner):
                calls.append(a);return dict(status='SUCCEEDED',run_id=owner)
            r=run_tail(self.result(),state,execute,lambda a:None)
            self.assertEqual(calls,['c','b']);self.assertEqual(r['small_accounts_verified'],['c','b'])
            self.assertEqual(r['account_order'],['a','c','b'])
            run_tail(self.result(),state,execute,lambda a:None)
            self.assertEqual(calls,['c','b'])
            self.assertFalse((state/'daily-ledger.json').exists())
    def test_failure_stops_before_c_and_safe_retry_is_bounded(self):
        with tempfile.TemporaryDirectory() as d,patch('cloud_small_account_chain.day_key',return_value=DAY):
            calls=[]
            def execute(a,owner):
                calls.append(a);raise DailyStageFailure('known safe failure',retry_allowed=True)
            with self.assertRaises(DailyStageFailure):run_tail(self.result(),Path(d),execute,lambda a:None)
            self.assertEqual(calls,['c','c'])
    def test_unknown_spend_never_retries(self):
        with tempfile.TemporaryDirectory() as d,patch('cloud_small_account_chain.day_key',return_value=DAY):
            calls=[]
            def execute(a,owner):
                calls.append(a);raise DailyStageFailure('uncertain receipt',retry_allowed=False)
            with self.assertRaises(DailyStageFailure):run_tail(self.result(),Path(d),execute,lambda a:None)
            self.assertEqual(calls,['c'])
    def test_completed_c_skipped_before_remaining_b(self):
        with tempfile.TemporaryDirectory() as d,patch('cloud_small_account_chain.day_key',return_value=DAY):
            state=Path(d);ledger=account_paths(state,'c').ledgers()['daily']
            ledger.begin(DAY);ledger.finish(DAY,'SUCCEEDED');calls=[]
            run_tail(self.result(),state,lambda a,o:(calls.append(a) or dict(status='SUCCEEDED',run_id=o)),lambda a:None)
            self.assertEqual(calls,['b'])
    def test_invalid_duplicate_order_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                run_tail(self.result(),Path(d),lambda *a:self.fail('game started'),lambda a:None,order=('c','c'))
            self.assertEqual(small_account_order({'small_accounts_after_full':['c','b']}),['c','b'])
    def test_a_incomplete_and_refresh_block_all_execution(self):
        with tempfile.TemporaryDirectory() as d:
            for result in (dict(mode='full',status='NEEDS_ATTENTION',day=DAY),self.result()):
                with patch('cloud_small_account_chain.day_key',return_value='2026-10-08'):
                    with self.assertRaises(RuntimeError):
                        run_tail(result,Path(d),lambda *a:self.fail('game started'),lambda a:None)

if __name__=='__main__':unittest.main()
