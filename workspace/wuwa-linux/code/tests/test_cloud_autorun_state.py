from datetime import datetime,timezone,timedelta
from pathlib import Path
import tempfile
import unittest
from cloud_autorun_state import DailyLedger,ProcessLock,day_key


class AutorunStateTests(unittest.TestCase):
    def test_reset_boundary(self):
        zone=timezone(timedelta(hours=8))
        self.assertEqual(day_key(datetime(2026,10,4,3,59,tzinfo=zone)),'2026-10-03')
        self.assertEqual(day_key(datetime(2026,10,4,4,0,tzinfo=zone)),'2026-10-04')
    def test_completed_or_failed_day_is_not_repeated(self):
        for status in ('SUCCEEDED','FAILED'):
            with tempfile.TemporaryDirectory() as folder:
                ledger=DailyLedger(Path(folder)/'ledger.json')
                self.assertTrue(ledger.begin('2026-10-04')[0])
                ledger.finish('2026-10-04',status)
                self.assertFalse(ledger.begin('2026-10-04')[0])
                self.assertTrue(ledger.begin('2026-10-05')[0])
    def test_crashed_previous_day_blocks_a_new_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ledger.json'
            DailyLedger(path).begin('2026-10-04')
            self.assertEqual(DailyLedger(path).begin('2026-10-05'),(False,'interrupted_run_needs_review'))
    def test_duplicate_process_lock_is_rejected_and_released(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lock'
            with ProcessLock(path):
                with self.assertRaises(RuntimeError):
                    with ProcessLock(path):pass
            with ProcessLock(path):pass


if __name__=='__main__':unittest.main()
