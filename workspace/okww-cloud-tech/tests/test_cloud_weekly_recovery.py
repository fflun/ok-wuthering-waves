import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from cloud_weekly_recovery import recovery, ResumeWeeklyCombat


class RecoveryTests(unittest.TestCase):
    def task(self):
        chars = [SimpleNamespace(index=i, is_current_char=i == 0) for i in range(3)]
        task = SimpleNamespace(chars=chars, popup=False, active=True, victory=False)
        task.ocr = lambda *a, **k: [1] if (task.popup if '复苏' in k['match'].pattern else task.active) else []
        task.combat_once = Mock(return_value=True)
        task._choose_switch_target = lambda current, *a, **k: next((c for c in task.chars if c and c != current), current)
        def switch(current):
            task._choose_switch_target(current, False)
            task.popup = True
            task.raise_not_in_combat('failed switch')
        task.switch_next_char = switch
        task.raise_not_in_combat = Mock(side_effect=RuntimeError('native failure'))
        task.get_current_char = lambda: next(c for c in chars if c.is_current_char)
        task.in_team = lambda: (True, 0, 3)
        task.close_revive_popup = lambda: setattr(task, 'popup', False)
        task.wait_until = lambda predicate, **k: predicate()
        task.load_chars = Mock()
        task.log_info = Mock()
        task.combat_end_condition = lambda: task.victory
        task.executor = SimpleNamespace(interaction=SimpleNamespace(held_keys=set(), held_buttons=set(), release_all=Mock()))
        return task

    def test_confirmed_dead_target_excluded_and_methods_restored(self):
        task = self.task()
        original = task._choose_switch_target
        chars = task.chars
        with recovery(task):
            with self.assertRaises(ResumeWeeklyCombat):
                task.switch_next_char(chars[0])
            self.assertIs(task._choose_switch_target(chars[0], False), chars[2])
            self.assertIs(task.chars, chars)
        self.assertIs(task._choose_switch_target, original)
        self.assertFalse(hasattr(task, '_cloud_weekly_handle_revive'))

    def test_unknown_popup_does_not_mark_any_slot_dead(self):
        task = self.task()
        with recovery(task):
            task.popup = True
            with self.assertRaises(ResumeWeeklyCombat): task._cloud_weekly_handle_revive()
            self.assertIs(task._choose_switch_target(task.chars[0], False), task.chars[1])

    def test_active_objective_resumes_native_combat_until_victory(self):
        task = self.task()
        native = task.combat_once
        native.side_effect = [False, True]
        def finished():
            return native.call_count == 2
        task.combat_end_condition = finished
        with recovery(task): self.assertTrue(task.combat_once())
        self.assertEqual(native.call_count, 2)

    def test_unknown_state_stops_without_retry(self):
        task = self.task()
        task.active = False
        native = task.combat_once
        with recovery(task), self.assertRaisesRegex(RuntimeError, 'without verified'):
            task.combat_once()
        self.assertEqual(native.call_count, 1)

    def test_explicit_named_hp_check_continues_original_combat_until_victory(self):
        task=self.task();task.active=False;native=task.combat_once
        task.combat_end_condition=lambda:native.call_count==2
        guard=Mock(return_value=True)
        with recovery(task,active_check=guard):self.assertTrue(task.combat_once())
        self.assertEqual(native.call_count,2);guard.assert_called_once()

    def test_unverified_named_hp_check_stops(self):
        task=self.task();task.active=False;native=task.combat_once
        with recovery(task,active_check=lambda:False),self.assertRaisesRegex(RuntimeError,'without verified'):
            task.combat_once()
        native.assert_called_once()

    def test_named_hp_check_retries_remain_bounded(self):
        task=self.task();task.active=False;native=task.combat_once
        with recovery(task,active_check=lambda:True),self.assertRaisesRegex(RuntimeError,'exhausted'):
            task.combat_once()
        self.assertEqual(native.call_count,5)

    def test_named_hp_callback_error_stops_and_restores_methods(self):
        task=self.task();task.active=False;native=task.combat_once
        with self.assertRaisesRegex(RuntimeError,'identity unknown'):
            with recovery(task,active_check=Mock(side_effect=RuntimeError('identity unknown'))):task.combat_once()
        self.assertIs(task.combat_once,native)
        self.assertFalse(hasattr(task,'_cloud_weekly_handle_revive'))

    def test_retries_bounded(self):
        task = self.task()
        native = task.combat_once
        with recovery(task), self.assertRaisesRegex(RuntimeError, 'exhausted'):
            task.combat_once()
        self.assertEqual(native.call_count, 5)

    def test_no_surviving_hud_stops(self):
        task = self.task()
        task.popup = True
        task.in_team = lambda: (False, -1, 0)
        with recovery(task), self.assertRaisesRegex(RuntimeError, 'no surviving'):
            task._cloud_weekly_handle_revive()

    def test_popup_after_native_return_recovers_before_reading_blurred_objective(self):
        task=self.task();native=task.combat_once
        def run():
            if native.call_count==1:
                task.popup=True;task.active=False
            else:task.victory=True
            return True
        native.side_effect=run
        def close():task.popup=False;task.active=True
        task.close_revive_popup=close
        with recovery(task):self.assertTrue(task.combat_once())
        self.assertEqual(native.call_count,2);self.assertFalse(task.popup)
    def test_existing_popup_is_closed_before_native_actions(self):
        task=self.task();task.popup=True;native=task.combat_once
        def run():
            self.assertFalse(task.popup);task.victory=True;return True
        native.side_effect=run
        with recovery(task):self.assertTrue(task.combat_once())
        native.assert_called_once()
    def test_post_return_popup_without_surviving_hud_stops(self):
        task=self.task();native=task.combat_once
        def run():task.popup=True;return True
        native.side_effect=run;task.in_team=lambda:(False,-1,0)
        with recovery(task),self.assertRaisesRegex(RuntimeError,'no surviving'):task.combat_once()
        native.assert_called_once()

    def test_medicine_enabled_resumes_original_combat_without_closing_popup(self):
        task=self.task();task.popup=True;task._cloud_use_revive_medicine=True
        task.reset_to_false=Mock();task.close_revive_popup=Mock();native=task.combat_once
        def revive(*args):task.popup=False;return 'medicine'
        def fight():task.victory=True;return 'native victory'
        native.side_effect=fight
        with patch('cloud_revive.medicine_or_heal',side_effect=revive) as use,recovery(task):
            self.assertEqual(task.combat_once(),'native victory')
        use.assert_called_once_with(task,None)
        task.close_revive_popup.assert_not_called();native.assert_called_once()

    def test_native_death_exception_uses_world_fallback_then_native_rotation(self):
        class CharDeadException(RuntimeError):pass
        task=self.task();task._cloud_use_revive_medicine=True;task.reset_to_false=Mock()
        native=task.combat_once
        def fight():
            if native.call_count==1:raise CharDeadException('native dead')
            task.victory=True;return True
        native.side_effect=fight
        with patch('cloud_revive.medicine_or_heal',return_value='world') as heal,recovery(task):
            self.assertTrue(task.combat_once())
        heal.assert_called_once_with(task,None)
        self.assertEqual(native.call_count,2)
