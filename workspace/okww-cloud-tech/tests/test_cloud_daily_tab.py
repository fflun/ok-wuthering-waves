import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from cloud_daily_guard import ensure_activity_tab


def task(titles, labels=None, icons=None):
    t=SimpleNamespace(next_frame=Mock(),sleep=Mock(),click_box=Mock())
    values=iter(titles)
    def ocr(*args):
        names=next(values) if args==(0,0,.32,.10) else (labels or [])
        return [SimpleNamespace(name=n) for n in names]
    t.ocr=ocr
    t.find_one=Mock(side_effect=icons or [SimpleNamespace(x=32,y=104)]*2)
    return t


class DailyTabTests(unittest.TestCase):
    def test_activity_page_never_clicked(self):
        t=task([['活跃行迹']]);self.assertFalse(ensure_activity_tab(t));t.click_box.assert_not_called()
    def test_unknown_page_never_clicked(self):
        t=task([['电台'],['电台']]);self.assertFalse(ensure_activity_tab(t));t.click_box.assert_not_called()
    def test_material_title_alone_insufficient(self):
        t=task([['素材获取'],['素材获取']],['模拟领域']);self.assertFalse(ensure_activity_tab(t));t.click_box.assert_not_called()
    def test_verified_material_returns_activity_once(self):
        t=task([['素材获取'],['素材获取'],['素材获取'],['活跃行迹']],['模拟领域','凝素领域','讨伐强敌'])
        self.assertTrue(ensure_activity_tab(t));t.click_box.assert_called_once()
    def test_changed_page_stops_before_click(self):
        t=task([['素材获取'],['素材获取'],['领取奖励']],['模拟领域','凝素领域','讨伐强敌'])
        with self.assertRaisesRegex(RuntimeError,'changed'):ensure_activity_tab(t)
        t.click_box.assert_not_called()
    def test_wrong_icon_location_rejected(self):
        t=task([['素材获取'],['素材获取']],['模拟领域','凝素领域','讨伐强敌'],[SimpleNamespace(x=700,y=450)])
        self.assertFalse(ensure_activity_tab(t));t.click_box.assert_not_called()
    def test_failed_return_stops_after_single_click(self):
        t=task([['素材获取']]*4,['模拟领域','凝素领域','讨伐强敌'])
        with self.assertRaisesRegex(RuntimeError,'did not return'):ensure_activity_tab(t)
        t.click_box.assert_called_once()


if __name__=='__main__':unittest.main()
