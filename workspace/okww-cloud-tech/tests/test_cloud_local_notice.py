import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cloud_failure_notice as notice
import main_cloud_autodaily as launcher
from cloud_autorun_state import write_json, day_key

class LocalNoticeTests(unittest.TestCase):
    def test_retry_and_recovered_are_audit_only_preserve_terminal_notice(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)
            write_json(state/'failure-notice.json',{'event':'FAILED','reason':'old terminal'})
            before=(state/'failure-notice.json').read_bytes()
            with patch.object(notice,'show_local_notice') as local, patch.object(notice.smtplib,'SMTP_SSL') as smtp:
                notice.notify_retry(state,'daily','first failure')
                notice.notify_recovered(state,'daily')
                local.assert_not_called();smtp.assert_not_called()
            self.assertEqual((state/'failure-notice.json').read_bytes(),before)
            rows=[json.loads(x) for x in (state/'notice-history.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['event'] for r in rows],['RETRYING','RECOVERED'])
            self.assertTrue(all(r['status']=='SUPPRESSED_POLICY' for r in rows))

    def test_local_only_readiness_and_missing_channel(self):
        self.assertTrue(notice.notification_ready({'local_enabled':True}))
        self.assertFalse(notice.notification_ready({'enabled':False}))

    def test_failure_dispatches_local_without_smtp(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)
            write_json(state/'notifications.json',{'local_enabled':True,'enabled':False})
            with patch.object(notice,'show_local_notice') as local, patch.object(notice.smtplib,'SMTP_SSL') as smtp:
                notice.notify_failure(state,'daily','test reason')
                local.assert_called_once_with(); smtp.assert_not_called()
            receipt=json.loads((state/'failure-notice.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'],'LOCAL_DISPATCHED')

    def test_notification_failure_preserves_local_record(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)
            write_json(state/'notifications.json',{'local_enabled':True,'enabled':False})
            with patch.object(notice,'show_local_notice',side_effect=RuntimeError('test')):
                notice.notify_failure(state,'daily','failed')
            receipt=json.loads((state/'failure-notice.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['local_status'],'SEND_FAILED')
            self.assertEqual(receipt['reason'],'failed')

    def test_finished_today_never_launches_game_with_local_only(self):
        import sys
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/'background';state.mkdir()
            write_json(state/'notifications.json',{'local_enabled':True,'enabled':False})
            write_json(state/'autorun-config.json',{'python':sys.executable,'runtime':d,'frozen_runtime':d,'browser_deps':d})
            write_json(state/'validation.json',dict.fromkeys(('synthetic_capture','game_capture','game_input','no_foreground_interference','native_daily_completed'),True)|{'source_hashes':{}})
            write_json(state/'daily-ledger.json',{day_key():{'status':'SUCCEEDED'}})
            with patch.object(launcher,'STATE',state),patch.object(launcher,'fingerprint',return_value={}),patch.object(launcher.subprocess,'Popen') as start:
                self.assertEqual(launcher.run()['status'],'SKIPPED')
                start.assert_not_called()

if __name__=='__main__':unittest.main()
