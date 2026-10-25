import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from cloud_nest_current import read_account

class AccountReadTests(unittest.TestCase):
    def task(self,values):
        return SimpleNamespace(next_frame=Mock(),frame=object(),sleep=Mock(),
            ocr=Mock(side_effect=[[SimpleNamespace(name=s)] for s in values]))
    def test_short_ocr_miss_then_stable_identifier(self):
        task=self.task(['','123456789','123456789'])
        with patch('cv2.resize',return_value=object()):self.assertEqual(read_account(task),'123456789')
        self.assertEqual(task.next_frame.call_count,3)
    def test_ambiguous_or_changing_identifier_never_accepted(self):
        for values in (['']*6,['123456789 987654321']*6,['123456789','987654321']*3):
            task=self.task(values)
            with patch('cv2.resize',return_value=object()),self.assertRaisesRegex(RuntimeError,'unreadable'):
                read_account(task)
            self.assertEqual(task.next_frame.call_count,6)
