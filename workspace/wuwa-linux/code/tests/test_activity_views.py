import unittest
from cloud_daily_guard import activity_from_views
class Tests(unittest.TestCase):
 def test_zero_detected_only_at_native_size(self):
  self.assertEqual(activity_from_views(['活跃行迹'],[['0'],[]]),0)
 def test_higher_activity_scaled_only(self):
  self.assertEqual(activity_from_views(['活跃行迹'],[[],['110']]),110)
 def test_views_agree(self):
  self.assertEqual(activity_from_views(['活跃行迹'],[['100'],['100']]),100)
 def test_empty_is_not_zero(self):
  with self.assertRaises(RuntimeError):activity_from_views(['活跃行迹'],[[],[]])
 def test_conflicting_views_stop(self):
  with self.assertRaises(RuntimeError):activity_from_views(['活跃行迹'],[['10'],['100']])
 def test_wrong_page_stops(self):
  with self.assertRaises(RuntimeError):activity_from_views(['素材获取'],[['0'],[]])
 def test_ambiguous_numbers_stop(self):
  with self.assertRaises(RuntimeError):activity_from_views(['活跃行迹'],[['0','20'],['0']])
if __name__=='__main__':unittest.main()
