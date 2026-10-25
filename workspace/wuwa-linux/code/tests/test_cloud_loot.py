import unittest
import ast
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace
from cloud_loot import claim_prompt, navigate_confirmed_reward


class LootTests(unittest.TestCase):
    def test_cloud_marker_does_not_require_disappearing_objective(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'cloud_loot.py').read_text())
        install=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='install')
        fn=next(n for n in install.body if isinstance(n,ast.FunctionDef) and n.name=='treasure')
        import re
        ns={'original_treasure':lambda task:None,'re':re,'claim_prompt':lambda task:None}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'cloud_loot.py','exec'),ns)
        for cloud,objective,phase,expected in [(False,True,False,False),(True,False,False,True),(True,True,False,True),(True,False,True,True)]:
            task=SimpleNamespace(is_browser=lambda:cloud,ocr=lambda *a,**k:['领取奖励'] if objective else [],
                                 box_of_screen=lambda *a,**k:object(),find_one=Mock(return_value='marker'),_cloud_reward_navigation=phase)
            self.assertEqual(ns['treasure'](task),'marker' if expected else None)
            self.assertEqual(task.find_one.called,expected)
            if expected:self.assertEqual(task.find_one.call_args.kwargs['threshold'],.70)
        prompt=object();ns['claim_prompt']=lambda task:prompt
        task=SimpleNamespace(is_browser=lambda:True,ocr=Mock(),find_one=Mock())
        self.assertIs(ns['treasure'](task),prompt)
        task.ocr.assert_not_called()
        task.find_one.assert_not_called()

    def test_navigation_scope_and_key_release_on_success_and_failure(self):
        for fails in (False,True):
            task=SimpleNamespace(executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock())))
            def walk():
                self.assertTrue(task._cloud_reward_navigation)
                if fails:raise RuntimeError('native movement failed')
                return 'arrived'
            if fails:
                with self.assertRaises(RuntimeError):navigate_confirmed_reward(task,walk)
            else:self.assertEqual(navigate_confirmed_reward(task,walk),'arrived')
            self.assertFalse(task._cloud_reward_navigation)
            task.executor.interaction.release_all.assert_called_once()

    def test_requires_actual_reward_text(self):
        reward=SimpleNamespace(name='领取奖励')
        def ocr(*rect,match):
            self.assertIsNotNone(match.search(reward.name))
            self.assertIsNone(match.search('吸收'))
            self.assertIsNone(match.search('确认'))
            return [reward]
        self.assertIs(claim_prompt(SimpleNamespace(ocr=ocr)),reward)
        self.assertIsNone(claim_prompt(SimpleNamespace(ocr=lambda *a,**kw:[])))

if __name__=='__main__': unittest.main()
