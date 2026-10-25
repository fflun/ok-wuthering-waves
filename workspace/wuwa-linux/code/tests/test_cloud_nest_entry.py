import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from cloud_nest_entry import select
from cloud_nest_state import TARGET, KEY


class EntryTests(unittest.TestCase):
    def make(self, change=False):
        rows = [SimpleNamespace(name='6/48',x=680,y=250,height=20),
                SimpleNamespace(name='41/41',x=680,y=350,height=20)]
        task = SimpleNamespace(openF2Book=Mock(),go_nest=Mock(),next_frame=Mock(),
                               height_of_screen=lambda f:720*f,count_re=None)
        task._make_nest_cache_key = lambda b,d: KEY if d=='41' else 'go_nest:48:18'
        def ocr(x,y,xx,yy,**kw):
            if x == .35:return rows
            if yy-y > .05:
                return [SimpleNamespace(name=TARGET if y>.4 else '梦枢天罗残象聚落')]
            return [SimpleNamespace(name='41/41' if y>.4 else ('7/48' if change else '6/48'))]
        task.ocr=ocr
        return task

    def test_default_never_selects_other_nest(self):
        self.assertEqual(select(self.make())[2:4],(TARGET,(41,41)))

    def test_explicit_permission_selects_one_unfinished(self):
        self.assertEqual(select(self.make(),True)[2:4],('梦枢天罗残象聚落',(6,48)))

    def test_count_mismatch_refuses_entry(self):
        with self.assertRaisesRegex(RuntimeError,'changed'):
            select(self.make(change=True),True)

    def test_pending_completed_nest_prevents_switch_to_unfinished(self):
        self.assertEqual(select(self.make(),True,{'key':KEY,'target':TARGET})[2:4],(TARGET,(41,41)))

    def test_pending_title_mismatch_refuses(self):
        with self.assertRaisesRegex(RuntimeError,'title'):
            select(self.make(),True,{'key':KEY,'target':'其他残象聚落'})
