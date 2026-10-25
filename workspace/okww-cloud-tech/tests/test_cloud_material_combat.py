import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cloud_material_combat import (Evidence, CompletionGate, CombatObservationError,
                                  material_active, require_completion, observe)
from test_cloud_native_flow import native_method


class MaterialCompletionTests(unittest.TestCase):
    def test_all_positive_and_negative_signals_must_agree(self):
        good = Evidence(reward=True, team=True)
        for change in ({'timer': True}, {'enemies': True}, {'unfinished': True},
                       {'team': False}, {'reward': False}, {'valid': False}, {'recovery': True}):
            with self.subTest(change=change):
                gate = CompletionGate()
                for t in (0, .5, 1.1, 3, 20):
                    self.assertNotEqual(gate.update(replace(good, **change), t, object()), 'COMPLETE')

    def test_victory_needs_three_distinct_observations_and_one_second(self):
        gate = CompletionGate()
        good = Evidence(reward=True, team=True)
        self.assertEqual([gate.update(good, t, object()) for t in (0, .1, .2)], ['PENDING']*3)
        self.assertEqual(gate.update(good, 1.1, object()), 'COMPLETE')

    def test_cached_frame_does_not_count_as_multiple_observations(self):
        gate = CompletionGate()
        frame = object()
        for t in (0, 1, 10, 20):
            self.assertEqual(gate.update(Evidence(reward=True, team=True), t, frame), 'PENDING')

    def test_new_wave_or_unknown_resets_victory_streak(self):
        for interruption in (Evidence(timer=True), Evidence(unfinished=True), Evidence(valid=False)):
            gate = CompletionGate()
            good = Evidence(reward=True, team=True)
            gate.update(good, 0, object())
            gate.update(good, .6, object())
            gate.update(interruption, .7, object())
            self.assertEqual(gate.update(good, 2, object()), 'PENDING')

    def task(self):
        return SimpleNamespace(executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock())),
                               log_info=Mock(), next_frame=Mock())

    def test_unknown_waits_without_input_and_recovers_on_enemy_evidence(self):
        task = self.task()
        with patch('cloud_material_combat.observe', side_effect=['UNKNOWN', 'ACTIVE']), patch('cloud_material_combat.time.sleep'):
            self.assertTrue(material_active(task))
        task.executor.interaction.release_all.assert_called_once()

    def test_unknown_times_out_instead_of_becoming_victory(self):
        task = self.task()
        with patch('cloud_material_combat.observe', return_value='UNKNOWN'), patch('cloud_material_combat.time.monotonic', side_effect=[0, 9]):
            with self.assertRaises(CombatObservationError): material_active(task)

    def test_recovery_during_unknown_is_not_active_or_victory(self):
        with patch('cloud_material_combat.observe', side_effect=['UNKNOWN', 'RECOVERY']), patch('cloud_material_combat.time.sleep'):
            self.assertFalse(material_active(self.task()))
        with patch('cloud_material_combat.settled', return_value='RECOVERY'):
            with self.assertRaises(CombatObservationError): require_completion(self.task(), 'reward_walk')

    def test_reward_boundary_discards_earlier_approval(self):
        task = self.task()
        task._cloud_material_exit = {'status': 'COMPLETE'}
        with patch('cloud_material_combat.settled', return_value='ACTIVE') as check:
            with self.assertRaises(CombatObservationError): require_completion(task, 'reward_walk')
            check.assert_called_once_with(task, fresh=True)
        self.assertIsNone(task._cloud_material_exit)

    def test_failed_recognition_is_unknown(self):
        task = self.task()
        with patch('cloud_material_combat.read_evidence', side_effect=RuntimeError('OCR unavailable')):
            self.assertEqual(observe(task, fresh=True), 'UNKNOWN')

    def test_native_exception_handler_does_not_swallow_uncertain_combat(self):
        method = native_method('src/combat/CombatCheck.py', 'CombatCheck', 'in_combat',
                               {'CombatObservationError': CombatObservationError})
        task = SimpleNamespace(do_check_in_combat=Mock(side_effect=CombatObservationError('unknown')))
        with self.assertRaises(CombatObservationError): method(task)
        self.assertFalse(task.in_sleep_check)

    def test_both_exit_boundaries_block_native_actions(self):
        tree = ast.parse((Path(__file__).resolve().parents[1]/'cloud_combat_exit.py').read_text(encoding='utf-8'))
        install = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'install')
        for name, original in (('end', 'original_end'), ('walk', 'original_walk')):
            fn = next(n for n in install.body if isinstance(n, ast.FunctionDef) and n.name == name)
            ns = {'release': Mock(), original: Mock(), 'prepare_loot': Mock()}
            exec(compile(ast.Module(body=[fn], type_ignores=[]), 'exit', 'exec'), ns)
            with patch('cloud_material_combat.applies', return_value=True), patch('cloud_material_combat.require_completion', side_effect=CombatObservationError('still active')):
                with self.assertRaises(CombatObservationError): ns[name](SimpleNamespace(is_browser=lambda:True))
            ns[original].assert_not_called()
            ns['prepare_loot'].assert_not_called()


if __name__ == '__main__': unittest.main()
