import io
import json
import os
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cloud_heal as heal


class HealingTests(unittest.TestCase):
    def selector_boxes(self):
        return [SimpleNamespace(name='切换地图',x=736,y=33),
                SimpleNamespace(name='罗伊冰原',x=720,y=100),
                SimpleNamespace(name='今州',x=722,y=430)]

    def test_selector_requires_unique_title_and_two_regions(self):
        boxes=self.selector_boxes()
        self.assertTrue(heal.map_selector(boxes))
        self.assertFalse(heal.map_selector(boxes[:2]))
        self.assertFalse(heal.map_selector(boxes+boxes[:1]))
        boxes[0].x=100
        self.assertFalse(heal.map_selector(boxes))

    def test_selector_cancel_needs_two_fresh_frames(self):
        task=Mock();task.ocr.return_value=self.selector_boxes()
        self.assertTrue(heal.close_map_selector(task))
        self.assertEqual(task.next_frame.call_count,2)
        task.send_key.assert_called_once_with('esc',after_sleep=.5)
        task.click.assert_not_called()

    def test_changed_selector_stops_without_input(self):
        task=Mock();task.ocr.side_effect=[self.selector_boxes(),[]]
        with self.assertRaisesRegex(RuntimeError,'changed before cancellation'):
            heal.close_map_selector(task)
        task.send_key.assert_not_called()

    def test_unknown_menu_never_cancelled(self):
        task=Mock();task.ocr.return_value=[SimpleNamespace(name='购买',x=736,y=33)]
        self.assertFalse(heal.close_map_selector(task))
        task.send_key.assert_not_called()

    def test_selector_closure_still_needs_actual_waypoint(self):
        task=Mock();task.ocr.return_value=self.selector_boxes()
        task.wait_until.side_effect=lambda f,**kw:f()
        with patch.object(heal,'candidates',side_effect=[[],[]]),patch.object(heal,'attempt') as move:
            with self.assertRaisesRegex(RuntimeError,'no waypoint verified'):heal.travel_to_heal(task)
            move.assert_not_called()
        task.send_key.assert_called_once()

    def test_selector_closure_uses_only_fresh_candidate(self):
        task=Mock();task.ocr.return_value=self.selector_boxes()
        point=object();task.wait_until.side_effect=lambda f,**kw:f()
        with patch.object(heal,'candidates',side_effect=[[],[point]]),patch.object(heal,'attempt',return_value=True) as move:
            heal.travel_to_heal(task)
            move.assert_called_once_with(task,point)
        task.send_key.assert_called_once()

    def test_map_search_excludes_sidebar(self):
        task=Mock(); task.find_feature.return_value=[]
        self.assertEqual(heal.candidates(task), [])
        task.box_of_screen.assert_called_once_with(.10,.10,.93,.93)
        self.assertTrue(all(c.kwargs['threshold']==.70 for c in task.find_feature.call_args_list))

    def city_task(self):
        task=Mock();task.wait_until.side_effect=lambda f,**kw:f()
        switch=SimpleNamespace(name='切换地图',x=1000,y=662)
        city=SimpleNamespace(name='今州城',x=978,y=105)
        menu=self.selector_boxes()+[city]
        task.ocr.side_effect=[[switch],[switch],menu,menu]
        return task,switch,city,menu

    def test_city_fallback_requires_fresh_menu_then_real_waypoint(self):
        task,switch,city,_=self.city_task();point=object()
        with patch.object(heal,'candidates',return_value=[point]):
            self.assertEqual(heal.city_waypoints(task),[point])
        self.assertEqual([c.args[0] for c in task.click_box.call_args_list],[switch,city])
        self.assertEqual(task.next_frame.call_count,5)
        task.send_key.assert_not_called()

    def test_city_fallback_unknown_map_sends_no_input(self):
        task=Mock();task.ocr.return_value=[]
        self.assertEqual(heal.city_waypoints(task),[])
        task.click_box.assert_not_called()

    def test_city_fallback_changed_map_sends_no_input(self):
        task,switch,_,_=self.city_task();task.ocr.side_effect=[[switch],[]]
        with self.assertRaisesRegex(RuntimeError,'map switch changed'):heal.city_waypoints(task)
        task.click_box.assert_not_called()

    def test_city_fallback_unknown_or_duplicate_city_never_selected(self):
        for duplicate in (False,True):
            task,switch,city,menu=self.city_task()
            menu=menu+[city] if duplicate else menu[:-1]
            task.ocr.side_effect=[[switch],[switch],menu]
            with self.assertRaisesRegex(RuntimeError,'not positively available'):heal.city_waypoints(task)
            task.click_box.assert_called_once_with(switch,after_sleep=.5)

    def test_city_fallback_wrong_position_rejected(self):
        task,switch,city,menu=self.city_task();city.x=100
        task.ocr.side_effect=[[switch],[switch],menu]
        with self.assertRaisesRegex(RuntimeError,'not positively available'):heal.city_waypoints(task)
        self.assertEqual(task.click_box.call_count,1)

    def test_city_fallback_changed_second_frame_never_selected(self):
        task,switch,_,menu=self.city_task();task.ocr.side_effect=[[switch],[switch],menu,[]]
        with self.assertRaisesRegex(RuntimeError,'city selection changed'):heal.city_waypoints(task)
        self.assertEqual(task.click_box.call_count,1)

    def test_city_fallback_no_anchor_never_teleports(self):
        task,_,_,_=self.city_task()
        with patch.object(heal,'candidates',return_value=[]),patch.object(heal,'attempt') as move:
            self.assertEqual(heal.city_waypoints(task),[])
            move.assert_not_called()

    def test_scroll_only_verified_middle_city_list_once(self):
        task=Mock()
        boxes=self.selector_boxes()+[SimpleNamespace(name=n,x=985,y=y) for n,y in [('归墟港市',180),('无光之森',245)]]
        task.ocr.return_value=boxes
        self.assertTrue(heal.rewind_city_regions(task,boxes))
        task.swipe_relative.assert_called_once_with(.86,.21,.86,.72,duration=.6)
        task.click_box.assert_not_called()

    def test_scroll_refuses_unknown_changed_or_present_city(self):
        task=Mock();boxes=self.selector_boxes()+[SimpleNamespace(name=n,x=985,y=y) for n,y in [('归墟港市',180),('无光之森',245)]]
        self.assertFalse(heal.rewind_city_regions(task,self.selector_boxes()))
        self.assertFalse(heal.rewind_city_regions(task,boxes+[SimpleNamespace(name='今州城',x=985,y=105)]))
        task.swipe_relative.assert_not_called()
        task.ocr.return_value=[]
        with self.assertRaisesRegex(RuntimeError,'changed before scroll'):heal.rewind_city_regions(task,boxes)
        task.swipe_relative.assert_not_called()

    def test_city_fallback_scroll_rechecks_name_then_actual_anchor(self):
        task,switch,city,_=self.city_task()
        middle=self.selector_boxes()+[SimpleNamespace(name=n,x=985,y=y) for n,y in [('归墟港市',180),('无光之森',245)]]
        top=self.selector_boxes()+[city]
        task.ocr.side_effect=[[switch],[switch],middle,middle,top,top]
        point=object()
        with patch.object(heal,'candidates',return_value=[point]):self.assertEqual(heal.city_waypoints(task),[point])
        self.assertEqual([c.args[0] for c in task.click_box.call_args_list],[switch,city])
        task.swipe_relative.assert_called_once()

    def test_scroll_same_region_crop_and_known_traditional_glyph(self):
        task=Mock()
        before=self.selector_boxes()+[SimpleNamespace(name=n,x=985,y=y) for n,y in
            [('归墟港市',180),('无光之森',245),('虎口山脈',486)]]
        after=self.selector_boxes()+[SimpleNamespace(name=n,x=985,y=y) for n,y in
            [('归墟港市',180),('无光之森',245),('虎口山脉',486)]]
        task.ocr.return_value=after
        self.assertTrue(heal.rewind_city_regions(task,before))
        task.ocr.assert_called_once_with(.50,0,1,.80)
        task.swipe_relative.assert_called_once()
        task.click_box.assert_not_called()

    def test_scroll_rejects_actual_changed_regions_despite_glyph_normalization(self):
        task=Mock()
        before=self.selector_boxes()+[SimpleNamespace(name=n,x=985,y=y) for n,y in
            [('归墟港市',180),('无光之森',245),('虎口山脈',486)]]
        task.ocr.return_value=self.selector_boxes()+[SimpleNamespace(name=n,x=985,y=y) for n,y in
            [('荒石高地',180),('无光之森',245),('虎口山脉',486)]]
        with self.assertRaisesRegex(RuntimeError,'changed before scroll'):
            heal.rewind_city_regions(task,before)
        task.swipe_relative.assert_not_called()

    def test_lower_map_waypoint_retained_overlay_excluded(self):
        task=Mock();task.frame=SimpleNamespace(shape=(720,1280,3))
        def box(x,y):return SimpleNamespace(x=x,y=y,width=12,height=20,confidence=.8)
        bottom=box(452,637);covered=box(219,140)
        task.find_feature.side_effect=[[bottom],[covered]]
        self.assertEqual(heal.candidates(task),[bottom])

    def test_no_click_without_verified_travel_text(self):
        task=Mock(); task.wait_until.return_value=None
        self.assertFalse(heal.attempt(task, object()))
        task.click_box.assert_not_called()

    def test_world_arrival_required(self):
        task=Mock(); task.wait_until.side_effect=[object(),False]
        self.assertFalse(heal.attempt(task, object()))
        self.assertEqual(task.wait_until.call_args.kwargs['time_out'],45)

    def test_ambiguous_travel_buttons_rejected(self):
        task=Mock(); task.ocr.return_value=[object(),object()]
        self.assertIsNone(heal.travel_button(task))

    def test_success_never_calls_model(self):
        task=Mock()
        with patch.object(heal,'candidates',return_value=[object()]), patch.object(heal,'attempt',return_value=True), patch.object(heal,'choose_recovery') as api:
            heal.travel_to_heal(task)
            api.assert_not_called()

    def api(self, decision):
        return lambda *a,**k: io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(decision)}}]}).encode())

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY':'synthetic-test-key'})
    def test_flash_selection_and_strict_validation(self):
        options=[dict(id=0,x=800,y=300,confidence=.8)]
        self.assertEqual(heal.choose_recovery(options,self.api({'candidate_id':0})),0)
        for d in ({'candidate_id':True},{'candidate_id':1},{'candidate_id':None},{'candidate_id':0,'command':'anything'}):
            with self.assertRaises(RuntimeError):heal.choose_recovery(options,self.api(d))

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY':'synthetic-test-key'})
    def test_auth_failure_stops_without_leaking_body(self):
        def fail(*a,**k):raise urllib.error.HTTPError('url',401,'private-body',{},None)
        with self.assertRaisesRegex(RuntimeError,'HTTP 401; stopping'):
            heal.choose_recovery([dict(id=0)],fail)

    @patch.dict(os.environ, {'OKWW_HEAL_DEEPSEEK':'1'})
    def test_model_recovery_rechecks_live_candidate(self):
        a=SimpleNamespace(x=500,y=300,confidence=.8)
        b=SimpleNamespace(x=800,y=300,confidence=.75)
        task=Mock()
        with patch.object(heal,'candidates',side_effect=[[a],[a,b],[]]), patch.object(heal,'attempt',return_value=False) as move, patch.object(heal,'choose_recovery',return_value=0):
            with self.assertRaisesRegex(RuntimeError,'recovery failed'):heal.travel_to_heal(task)
            self.assertEqual(move.call_count,1)

    @patch.dict(os.environ, {'OKWW_HEAL_DEEPSEEK':'1'})
    def test_single_bounded_recovery(self):
        a=SimpleNamespace(x=500,y=300,confidence=.8)
        b=SimpleNamespace(x=800,y=300,confidence=.75)
        task=Mock()
        with patch.object(heal,'candidates',side_effect=[[a],[a,b],[b]]), patch.object(heal,'attempt',side_effect=[False,True]) as move, patch.object(heal,'choose_recovery',return_value=0) as api:
            heal.travel_to_heal(task)
            self.assertEqual(move.call_count,2);api.assert_called_once()

if __name__=='__main__':unittest.main()
