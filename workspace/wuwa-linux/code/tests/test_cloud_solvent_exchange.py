import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
import numpy as np

import cloud_daily_policy as policy

class SolventExchangeTests(unittest.TestCase):
    def test_exact_cost_and_materials(self):
        for current,target,units in [(1,60,1),(39,120,2),(99,120,1)]:
            self.assertEqual(policy.parse_solvent_exchange(f'兑换次数：{units}',f'结晶溶剂×{units}',f'结晶波片x{units*60}',current,target),(units,units*60))

    def test_missing_name_premium_wrong_amount_and_excess_are_rejected(self):
        for label,material,reward in [('兑换次数:1','晶溶剂×1','结晶波片×60'),('兑换次数:1','星声×60','结晶波片×60'),('兑换次数:1','结晶溶剂×1','结晶波片×120'),('兑换次数:2','结晶溶剂×2','结晶波片×120'),('兑换次数:3','结晶溶剂×3','结晶波片×180')]:
            with self.subTest(material=material,reward=reward):
                with self.assertRaises(RuntimeError):policy.parse_solvent_exchange(label,material,reward,1,60)

    def task(self,values):
        state={'index':-1}
        def fresh():state['index']+=1
        def ocr(*rect,frame):
            self.assertEqual(frame.shape,(1440,2560,3))
            position=0 if rect[0]==.25 else 1 if rect[0]==.29 else 2
            return [SimpleNamespace(name=values[state['index']][position])]
        def wait(fn,**kw):
            for _ in values:
                result=fn()
                if result:return result
            raise RuntimeError('observation timeout')
        return SimpleNamespace(next_frame=fresh,frame=np.zeros((720,1280,3),np.uint8),ocr=ocr,sleep=Mock(),wait_until=wait)

    def test_animation_is_not_accepted_until_two_complete_reads(self):
        rows=[('兑换次数:1','晶溶剂×1','结晶波片×60'),('兑换次数:1','结晶溶剂×1','结晶波片×60'),('兑换次数:1','结晶溶剂×1','结晶波片×60')]
        self.assertEqual(policy.verified_solvent_exchange(self.task(rows),1,60),(1,60))

    def test_a_single_correct_frame_cannot_authorize_exchange(self):
        rows=[('兑换次数:1','结晶溶剂×1','结晶波片×60'),('兑换次数:1','晶溶剂×1','结晶波片×60')]
        with self.assertRaises(RuntimeError):policy.verified_solvent_exchange(self.task(rows),1,60)

if __name__=='__main__':unittest.main()
