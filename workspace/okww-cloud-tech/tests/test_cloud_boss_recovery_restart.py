import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from cloud_all_boss import finish_verified_entry,manage_named_interactions


class RecoveryRestartTests(unittest.TestCase):
    def test_native_next_round_restarts_after_in_fight_reentry(self):
        # Execute the unchanged upstream loop without loading its Windows UI.
        source=Path(__file__).resolve().parents[1]/'src/task/FarmEchoTask.py'
        tree=ast.parse(source.read_text(encoding='utf8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FarmEchoTask')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='do_run')
        module=ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[]))
        namespace={'time':__import__('time'),'logger':Mock(),'TaskDisabledException':type('TaskDisabledException',(Exception,),{})}
        exec(compile(module,str(source),'exec'),namespace)
        task=SimpleNamespace(config={'Repeat Farm Count':2,'Boss':'Nameless Explorer'},_just_entered_boss_realm=True,
            combat_wait_time=0,bypass_end_wait=False,rounds=0)
        for name in ('manage_boss_parameters','init_parameters','in_realm_check',
                     'manage_boss_interactions','send_key','wait_click_feature',
                     'wait_in_team_and_world','sleep','log_info','log_debug','check_boss_name'):
            setattr(task,name,Mock())
        legacy=Mock(side_effect=RuntimeError('old world map flow'))
        task.in_team=lambda:(True,0,3);task.check_health_bar=lambda:False
        task.ocr=lambda *a:[SimpleNamespace(name='领取奖励')]
        task.manage_boss_interactions=lambda:manage_named_interactions(task,task.rounds,None,legacy) if task.rounds else None
        task.in_realm=lambda:True
        task.teleport_to_boss_enabled=lambda:False
        task.in_combat=lambda *a,**k:False
        task.in_world=lambda:False
        task.pick_echo=lambda:True
        task.wait_until=lambda *a,**k:False
        task.should_reteleport_after_farm_exception=lambda:False
        def fight(**kwargs):
            # Native teleport during recovery leaves this marker True.
            task._just_entered_boss_realm=True
            finish_verified_entry(task)
        task.combat_once=Mock(side_effect=fight)
        task.incr_drop=lambda dropped:setattr(task,'rounds',task.rounds+1)
        namespace['do_run'](task)
        self.assertEqual(task.rounds,2)
        self.assertEqual(task.combat_once.call_count,2)
        task.wait_click_feature.assert_called_once()
        self.assertFalse(task._just_entered_boss_realm)
        legacy.assert_not_called()

    def test_active_unknown_pending_or_other_profile_keeps_native_interactions(self):
        for objective,completed,pending,profile,enemies in (
                ('击败敌人',1,None,'Nameless Explorer',True),
                ('',1,None,'Nameless Explorer',False),
                ('领取奖励',0,None,'Nameless Explorer',False),
                ('领取奖励',1,{'round':2},'Nameless Explorer',False),
                ('领取奖励',1,None,'Other',False)):
            with self.subTest(objective=objective,completed=completed,pending=pending,profile=profile):
                task=SimpleNamespace(config={'Boss':profile},_in_realm=True,
                    in_team=lambda:(True,0,3),check_health_bar=lambda:enemies,
                    ocr=lambda *a:[SimpleNamespace(name=objective)],log_info=Mock())
                native=Mock();manage_named_interactions(task,completed,pending,native)
                native.assert_called_once()

    def test_finishing_entry_preserves_other_navigation_and_combat_state(self):
        task=SimpleNamespace(_just_entered_boss_realm=True,_in_realm=True,
            treat_as_not_in_realm=False,is_revived=False,_has_treasure=True)
        before=dict(task.__dict__)
        finish_verified_entry(task)
        before['_just_entered_boss_realm']=False
        self.assertEqual(task.__dict__,before)


if __name__=='__main__':unittest.main()
