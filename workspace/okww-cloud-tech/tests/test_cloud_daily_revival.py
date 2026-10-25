import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from cloud_daily_guard import run_tacet_daily


class Revived(Exception):pass


class DailyRevivalTests(unittest.TestCase):
    def args(self):
        material=SimpleNamespace(executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock())),log_info=Mock())
        return dict(material=material,recheck=Mock(return_value=(60,False)),
            check_day=Mock(),assert_clear=Mock(),recover=Mock(),revived_error=Revived)

    def test_verified_revival_uses_fresh_spending_and_original_config(self):
        args=self.args();config={'Which Tacet Suppression to Farm':1}
        native=Mock(side_effect=[Revived(), 'completed'])
        self.assertEqual(run_tacet_daily(native,used_stamina=0,config=config,**args),'completed')
        self.assertEqual([call.kwargs['used_stamina'] for call in native.call_args_list],[0,60])
        self.assertTrue(all(call.kwargs['config'] is config for call in native.call_args_list))
        self.assertEqual(args['recover'].call_count,2)
        self.assertIsNone(args['material']._cloud_material_exit)

    def test_activity_or_stamina_already_complete_does_not_reenter(self):
        for values in ((180,False),(80,True)):
            args=self.args();args['recheck'].return_value=values
            native=Mock(side_effect=Revived())
            run_tacet_daily(native,**args)
            self.assertEqual(native.call_count,1)

    def test_unverified_healing_blocks_combat(self):
        args=self.args();args['recover'].side_effect=RuntimeError('full HP unknown')
        native=Mock()
        with self.assertRaisesRegex(RuntimeError,'full HP unknown'):run_tacet_daily(native,**args)
        native.assert_not_called()

    def test_pending_and_day_change_block_reentry(self):
        for key in ('check_day','assert_clear'):
            args=self.args();args[key].side_effect=[None,None,RuntimeError('stop')]
            native=Mock(side_effect=Revived())
            with self.assertRaisesRegex(RuntimeError,'stop'):run_tacet_daily(native,**args)
            self.assertEqual(native.call_count,1)
            args['recheck'].assert_not_called()

    def test_other_errors_do_not_retry(self):
        args=self.args();native=Mock(side_effect=RuntimeError('reward unknown'))
        with self.assertRaisesRegex(RuntimeError,'reward unknown'):run_tacet_daily(native,**args)
        args['recheck'].assert_not_called()

    def test_recovery_is_bounded(self):
        args=self.args();native=Mock(side_effect=Revived())
        with self.assertRaisesRegex(RuntimeError,'limit reached'):run_tacet_daily(native,**args)
        self.assertEqual(native.call_count,3)
        self.assertEqual(args['recheck'].call_count,2)

    def test_actual_native_tacet_death_returns_to_same_target_with_new_budget(self):
        # Execute the saved native method, including a verified claim followed
        # by a death. Its second entry must use the live task-page spending.
        tree=ast.parse((Path(__file__).parents[1]/'src/task/TacetTask.py').read_text(encoding='utf-8'))
        method=next(m for c in tree.body if isinstance(c,ast.ClassDef)
                    for m in c.body if isinstance(m,ast.FunctionDef) and m.name=='farm_tacet')
        ns={};exec(compile(ast.Module(body=[method],type_ignores=[]),'native_tacet','exec'),ns)
        claims=[];entries=[]
        args=self.args();t=args['material'];t.config={};t.stamina_once=60
        for name in ('sleep','info_incr','openF2Book','open_boss_book','click_team_challenge',
                     'wait_in_team_and_world','walk_to_treasure','pick_f','click_relative','wait_click_skip_dialog_confirm'):
            setattr(t,name,Mock())
        t.get_stamina=lambda:(240,0,240)
        t.teleport_to_tacet=lambda index:entries.append(index)
        t.combat_once=Mock(side_effect=[None,Revived(),None])
        t.has_claim_stamina=lambda:True
        def claim(**kw):
            claims.append(kw['must_use']);return (len(claims)==1,60)
        t.use_stamina=claim
        config={'Which Tacet Suppression to Farm':2}
        run_tacet_daily(lambda **kw:ns['farm_tacet'](t,**kw),config=config,**args)
        self.assertEqual(entries,[1,1]);self.assertEqual(claims,[180,120])

    def test_scope_keeps_probe_and_non_daily_native_routes(self):
        source=(Path(__file__).parents[1]/'cloud_daily_guard.py').read_text(encoding='utf-8')
        self.assertIn('if not probe and task.is_browser()',source)
        self.assertIn('if not daily:return native_material',source)


if __name__=='__main__':unittest.main()
