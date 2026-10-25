import unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from contextlib import nullcontext
from main_cloud_daily import prepare_daily_team
def task(moved=False,known=True):
 active=SimpleNamespace(next_frame=Mock(),sleep=Mock(),click_box=Mock(),ensure_main=Mock())
 reads=[0]
 def ocr(*a,**kw):
  if kw['match'].pattern=='^挑战失败$':return [SimpleNamespace(name='挑战失败')] if known else []
  reads[0]+=1;return [SimpleNamespace(name='退出副本',x=400+(100 if moved and reads[0]>1 else 0),y=600)]
 active.ocr=Mock(side_effect=ocr);return active
class Tests(unittest.TestCase):
 def invoke(self,active,pending):
  with patch('cloud_revive.recovery_navigation',return_value=nullcontext()),patch('cloud_revive.world_heal_and_reenter'):
   prepare_daily_team(active,pending)
 def test_stable_failure_leaves_once(self):
  a=task()
  with tempfile.TemporaryDirectory() as folder:self.invoke(a,Path(folder)/'pending')
  a.click_box.assert_called_once();a.ensure_main.assert_called_once()
 def test_unknown_page_does_not_click(self):
  a=task(known=False)
  with tempfile.TemporaryDirectory() as folder:self.invoke(a,Path(folder)/'pending')
  a.click_box.assert_not_called()
 def test_changed_exit_stops_without_input(self):
  a=task(moved=True)
  with tempfile.TemporaryDirectory() as folder:
   with self.assertRaises(RuntimeError):self.invoke(a,Path(folder)/'pending')
  a.click_box.assert_not_called();a.ensure_main.assert_not_called()
 def test_pending_claim_blocks_all_navigation(self):
  a=task()
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'pending';path.write_text('{}')
   with self.assertRaises(RuntimeError):self.invoke(a,path)
  a.ocr.assert_not_called();a.click_box.assert_not_called()
if __name__=='__main__':unittest.main()
