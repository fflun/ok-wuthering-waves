import unittest
from types import SimpleNamespace as B
from unittest.mock import Mock
import cloud_heal as heal

class CountryFallbackTests(unittest.TestCase):
    def menu(self):
        return [B(name='切换地图',x=736,y=33),B(name='罗伊冰原',x=720,y=100),
            B(name='黎那汐塔',x=720,y=340),B(name='黑海岸',x=720,y=410),
            B(name='瑝珑',x=720,y=480),B(name='陷足流川',x=980,y=370)]
    def test_two_observations_select_named_country_only(self):
        task=Mock();task.ocr.return_value=self.menu()
        self.assertTrue(heal.select_huanglong_regions(task,self.menu()))
        self.assertEqual(task.click_box.call_args.args[0].name,'瑝珑')
        task.click_box.assert_called_once();task.next_frame.assert_called_once()
        task.ocr.assert_called_once_with(.50,0,1,.80)
    def test_unknown_country_or_purchase_page_never_clicked(self):
        for boxes in ([],self.menu()[:4],self.menu()+[B(name='瑝珑',x=721,y=490)],
                      [B(name='瑝珑',x=720,y=480),B(name='购买',x=736,y=33)]):
            task=Mock();self.assertFalse(heal.select_huanglong_regions(task,boxes));task.click_box.assert_not_called()
    def test_jinzhou_regions_not_toggled_or_collapsed(self):
        for extra in ([B(name='今州城',x=980,y=105)],
                      [B(name='荒石高地',x=980,y=200),B(name='归墟港市',x=980,y=280)]):
            task=Mock();self.assertFalse(heal.select_huanglong_regions(task,self.menu()+extra));task.click_box.assert_not_called()
    def test_changed_second_frame_stops_before_selection(self):
        for boxes in ([],[B(name=b.name,x=b.x+20,y=b.y) for b in self.menu()]):
            task=Mock();task.ocr.return_value=boxes
            with self.assertRaisesRegex(RuntimeError,'changed before selection'):
                heal.select_huanglong_regions(task,self.menu())
            task.click_box.assert_not_called()
    def test_named_subregion_requires_two_frames_and_not_city_row(self):
        boxes=self.menu()+[B(name='今州',x=728,y=540)]
        task=Mock();task.ocr.return_value=boxes
        self.assertTrue(heal.select_jinzhou_subregion(task,boxes))
        self.assertEqual(task.click_box.call_args.args[0].name,'今州')
        for values in (self.menu(),boxes+[B(name='今州城',x=980,y=105)],
                       self.menu()+[B(name='今州',x=980,y=540)]):
            task=Mock();self.assertFalse(heal.select_jinzhou_subregion(task,values));task.click_box.assert_not_called()
    def test_changed_subregion_cannot_select(self):
        boxes=self.menu()+[B(name='今州',x=728,y=540)]
        task=Mock();task.ocr.return_value=self.menu()
        with self.assertRaisesRegex(RuntimeError,'subregion changed'):
            heal.select_jinzhou_subregion(task,boxes)
        task.click_box.assert_not_called()

if __name__=='__main__':unittest.main()
