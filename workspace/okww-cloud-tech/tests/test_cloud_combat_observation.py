import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from test_cloud_native_flow import native_method

class CloudCombatObservationTests(unittest.TestCase):
    def test_all_material_tasks_share_completion_gate(self):
        from src.task.ForgeryTask import ForgeryTask
        from src.task.SimulationTask import SimulationTask
        from src.task.TacetTask import TacetTask
        from unittest.mock import patch
        import re
        method=native_method('src/combat/CombatCheck.py','CombatCheck','cloud_domain_still_active',{'time':SimpleNamespace(monotonic=lambda:20),'re':re})
        for kind in (ForgeryTask, SimulationTask, TacetTask):
            task=kind.__new__(kind)
            task.is_browser=lambda:True
            with patch('cloud_material_combat.material_active',return_value=True) as gate:
                self.assertTrue(method(task))
                gate.assert_called_once_with(task)
            task.is_browser=lambda:False
            with patch('cloud_material_combat.material_active') as gate:
                self.assertFalse(method(task))
                gate.assert_not_called()

    def test_lost_lock_with_positive_domain_evidence_keeps_rotation(self):
        method=native_method('src/combat/CombatCheck.py','CombatCheck','do_check_in_combat')
        for evidence in (True,False):
            scene=SimpleNamespace(in_combat=lambda:None,set_in_combat=Mock(return_value=True))
            task=SimpleNamespace(in_liberation=False,_in_combat=True,scene=scene,
                check_f_break=Mock(),get_current_char=lambda:None,on_combat_check=lambda:True,
                has_target=lambda:False,combat_end_condition=None,target_enemy=lambda **k:False,
                should_check_monthly_card=lambda:False,cloud_domain_still_active=lambda:evidence,
                reset_to_false=Mock(return_value=False))
            self.assertEqual(method(task,False),evidence)
            self.assertEqual(task.reset_to_false.call_count,0 if evidence else 1)

    def test_cloud_lock_cooldown_does_not_toggle_again(self):
        clock=SimpleNamespace(monotonic=Mock(return_value=10))
        method=native_method('src/combat/CombatCheck.py','CombatCheck','target_enemy',{'time':clock})
        task=SimpleNamespace(is_browser=lambda:True,has_target=lambda:False,
            _cloud_last_lock_request=9,middle_click=Mock())
        self.assertFalse(method(task))
        task.middle_click.assert_not_called()

    def test_one_lock_request_then_observe(self):
        clock=SimpleNamespace(monotonic=Mock(side_effect=[10,10,10.1,10.4]))
        method=native_method('src/combat/CombatCheck.py','CombatCheck','target_enemy',{'time':clock})
        task=SimpleNamespace(is_browser=lambda:True,has_target=lambda:False,
            middle_click=Mock(),next_frame=Mock())
        self.assertFalse(method(task))
        task.middle_click.assert_called_once_with()
        task.next_frame.assert_called_once_with()
