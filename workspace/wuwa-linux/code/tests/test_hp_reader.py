import unittest,numpy as np
from types import SimpleNamespace
from unittest.mock import Mock
from cloud_revive import health
def task(values):return SimpleNamespace(frame=np.zeros((720,1280,3),dtype=np.uint8),ocr=Mock(side_effect=values))
class Tests(unittest.TestCase):
 def test_3x_read_preferred_over_wide_truncation(self):
  self.assertEqual(health(task([['17130/17130'],['130/17130']])),(17130,17130))
 def test_partial_hp_not_upgraded_by_full_wide_read(self):
  self.assertEqual(health(task([['13751/17130'],['17130/17130']])),(13751,17130))
 def test_missing_slash_only_falls_back_to_printed_pair(self):
  self.assertEqual(health(task([['17130717130'],['17130/17130']])),(17130,17130))
 def test_two_missing_pairs_remain_unknown(self):
  self.assertIsNone(health(task([['17130717130'],[]])))
 def test_zero_is_not_full(self):
  self.assertEqual(health(task([['0/17130'],['17130/17130']])),(0,17130))
if __name__=='__main__':unittest.main()
