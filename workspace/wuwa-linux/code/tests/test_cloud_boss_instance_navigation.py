import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from cloud_all_boss import retain_named_instance,prepare_named_entry


class InstanceNavigationTests(unittest.TestCase):
    target={'name':'无铭探索者','aliases':['無銘探索者']}

    def task(self,title='Lv.90 无铭探索者·失轨囚影',objective='击败敌人',count=3):
        task=SimpleNamespace(in_team=lambda:(True,0,count),log_info=Mock(),
                             next_frame=Mock(),check_health_bar=lambda:False)
        task.ocr=lambda *area,**kwargs: [] if kwargs else [SimpleNamespace(name=title if area[1]==0 else objective)]
        return task

    def test_verified_instance_preserves_native_approach(self):
        source=Path(__file__).resolve().parents[1]/'src/task/FarmEchoTask.py'
        tree=ast.parse(source.read_text(encoding='utf8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FarmEchoTask')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_handle_unnamed_explorer')
        module=ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[]))
        namespace={};exec(compile(module,str(source),'exec'),namespace)
        task=self.task();native_map=Mock(side_effect=RuntimeError('boss not found'))
        task.teleport_to_nearest_boss=lambda:retain_named_instance(task,self.target,native_map)
        task.in_combat=Mock(return_value=False)
        task.find_treasure_icon=lambda:False;task.find_f_with_text=lambda:False
        task.sleep=Mock();task._has_treasure=False
        task.run_until=Mock();task.execute_treasure_hunt=Mock();task.wait_until=Mock()
        namespace['_handle_unnamed_explorer'](task)
        native_map.assert_not_called()
        task.run_until.assert_called_once()
        self.assertEqual(task.run_until.call_args.args[1],'w')
        self.assertEqual(task.run_until.call_args.kwargs['time_out'],12)
        self.assertTrue(task._cloud_weekly_trial)

    def test_wrong_target_uses_original_navigation(self):
        task=self.task(title='天傀劫煞');native=Mock(return_value='native')
        self.assertEqual(retain_named_instance(task,self.target,native),'native')
        native.assert_called_once()
        self.assertFalse(hasattr(task,'_cloud_weekly_trial'))

    def test_cleared_or_unknown_objective_uses_original_navigation(self):
        for objective in ('领取奖励','', '探索世界'):
            with self.subTest(objective=objective):
                task=self.task(objective=objective);native=Mock()
                retain_named_instance(task,self.target,native)
                native.assert_called_once()

    def test_incomplete_team_uses_original_navigation(self):
        task=self.task(count=2);native=Mock()
        retain_named_instance(task,self.target,native)
        native.assert_called_once()

    def test_alias_and_normalized_title(self):
        task=self.task(title='Lv.90 無銘 探索者・失轨囚影');native=Mock()
        retain_named_instance(task,self.target,native)
        native.assert_not_called()

    def test_new_entry_enables_existing_protection_before_native_wait(self):
        task=self.task();task.next_frame=Mock()
        native=Mock(return_value='original result')
        self.assertEqual(prepare_named_entry(task,self.target,native),'original result')
        native.assert_called_once();task.next_frame.assert_called_once()
        self.assertTrue(task._cloud_weekly_trial)
        # The upstream sleep happens after this returned entry, before combat_once.
        self.assertTrue(task._cloud_weekly_trial and '击败敌人' in task.ocr(0,.21,1,.31)[0].name)

    def test_unverified_new_entry_does_not_enable_protection(self):
        for title,objective,count in [('wrong','击败敌人',3),('无铭探索者','领取奖励',3),('无铭探索者','击败敌人',2)]:
            task=self.task(title=title,objective=objective,count=count);task.next_frame=Mock()
            prepare_named_entry(task,self.target,Mock())
            self.assertFalse(hasattr(task,'_cloud_weekly_trial'))

    def test_native_entry_failure_does_not_enable_protection(self):
        task=self.task();task.next_frame=Mock()
        with self.assertRaisesRegex(RuntimeError,'native failure'):
            prepare_named_entry(task,self.target,Mock(side_effect=RuntimeError('native failure')))
        self.assertFalse(hasattr(task,'_cloud_weekly_trial'));task.next_frame.assert_not_called()


if __name__=='__main__':unittest.main()
