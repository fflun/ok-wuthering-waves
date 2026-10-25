"""Replay real cloud crops through the original ring-shape detector."""
import ast
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal, ROUND_UP, ROUND_DOWN
from unittest.mock import Mock, patch
import cv2
import numpy as np
from cloud_concerto import install, normalize_ring_color

ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/'src/task/BaseCombatTask.py').read_text(encoding='utf-8'))
COLORS=ast.literal_eval(next(n.value for n in TREE.body if isinstance(n,ast.Assign)
    and any(isinstance(t,ast.Name) and t.id=='con_colors' for t in n.targets)))
NODE=next(n for c in TREE.body if isinstance(c,ast.ClassDef) and c.name=='BaseCombatTask'
          for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='count_rings')
def bounds(c):
    return np.array([c[k][0] for k in ('b','g','r')]),np.array([c[k][1] for k in ('b','g','r')])
NS=dict(cv2=cv2,np=np,Decimal=Decimal,ROUND_UP=ROUND_UP,ROUND_DOWN=ROUND_DOWN,color_range_to_bound=bounds)
exec(compile(ast.Module(body=[NODE],type_ignores=[]),'native-count-rings','exec'),NS)
NATIVE=NS['count_rings']
FIXTURES=ROOT/'tests/fixtures/cloud_concerto'


class ConcertoTests(unittest.TestCase):
    def task(self,browser=True):
        class Task:
            count_rings=NATIVE
            logger=Mock()
            def is_browser(self):return browser
            def get_current_con(self):return 'protected'
        protected=Task.get_current_con
        with patch.dict(sys.modules,{'src.task.BaseCombatTask':SimpleNamespace(BaseCombatTask=Task)}):
            install()
            installed=Task.count_rings
            install()
            self.assertIs(Task.count_rings,installed)
        self.assertIs(Task.get_current_con,protected)
        return Task()

    def test_real_cloud_positive_and_nearly_full_negative(self):
        task=self.task()
        for case in json.loads((FIXTURES/'manifest.json').read_text()):
            with self.subTest(case=case['name']):
                frame=cv2.imread(str(FIXTURES/(case['name']+'.png')))
                color=COLORS[case['element']]
                area,full=task.count_rings(frame,color,1500/9)
                self.assertEqual(full,case['full'])
                if full:
                    self.assertFalse(NATIVE(task,frame,color,1500/9)[1])
                    self.assertGreater(area,0)

    def test_local_game_preserves_native_results(self):
        task=self.task(False)
        for case in json.loads((FIXTURES/'manifest.json').read_text()):
            frame=cv2.imread(str(FIXTURES/(case['name']+'.png')));c=COLORS[case['element']]
            self.assertEqual(task.count_rings(frame,c,1500/9),NATIVE(task,frame,c,1500/9))

    def test_wrong_element_and_missing_hud_do_not_become_full(self):
        task=self.task()
        wind=cv2.imread(str(FIXTURES/'wind_full_a.png'))
        self.assertFalse(task.count_rings(wind,COLORS[2],1500/9)[1])
        for level in (0,120,255):
            image=np.full((42,42,3),level,dtype=np.uint8)
            for c in COLORS:self.assertFalse(task.count_rings(image,c,1500/9)[1])

    def test_untested_elements_remain_native(self):
        task=self.task();image=cv2.imread(str(FIXTURES/'wind_full_a.png'))
        for index in (0,1,3,5):
            self.assertEqual(task.count_rings(image,COLORS[index],1500/9),NATIVE(task,image,COLORS[index],1500/9))

if __name__=='__main__':unittest.main()
