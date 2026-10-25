import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from cloud_combat_exit import prepare_loot

class ExitTests(unittest.TestCase):
    def test_echo_overlay_cancel_only_with_positive_dialog_and_echo_scope(self):
        from cloud_combat_exit import close_echo_reward_overlay
        for scope,dialog in [(False,True),(True,False),(True,True)]:
            task=self.task([(True,0,3)])
            task._cloud_echo_only=scope;task.has_claim=Mock(return_value=dialog)
            task.send_key=Mock();task.next_frame=Mock()
            self.assertEqual(close_echo_reward_overlay(task),scope and dialog)
            if scope and dialog:task.send_key.assert_called_once_with('esc',after_sleep=0)
            else:task.send_key.assert_not_called()

    def test_echo_overlay_cancellation_precedes_active_domain_check(self):
        from cloud_combat_exit import retry_missing_team
        task=self.task([(False,-1,0)])
        task._cloud_echo_only=True;task.is_browser=lambda:True
        task.has_claim=lambda:True;task.send_key=Mock();task.next_frame=Mock()
        task.cloud_domain_still_active=Mock(side_effect=AssertionError('dialog must be closed first'))
        self.assertTrue(retry_missing_team(task,0))
        task.cloud_domain_still_active.assert_not_called()
    def test_missing_team_retry_is_bounded_and_cloud_only(self):
        from cloud_combat_exit import retry_missing_team
        for browser,active in [(False,True),(True,False),(True,True)]:
            task=SimpleNamespace(is_browser=lambda:browser,cloud_domain_still_active=lambda:active,
                switch_char_time_out=5,log_info=Mock(),next_frame=Mock())
            self.assertEqual(retry_missing_team(task,1),browser and active)
            if browser and active:
                with self.assertRaises(RuntimeError): retry_missing_team(task,6)

    def task(self, indices):
        interaction = SimpleNamespace(held_keys={'w'}, held_buttons={'left'}, release_all=Mock())
        mornye = type('Mornye', (), {})()
        mornye.index = 2
        mornye.switch_other_char = Mock()
        return SimpleNamespace(executor=SimpleNamespace(interaction=interaction),
            log_info=Mock(), sleep=Mock(), in_team=Mock(side_effect=indices),
            chars=[SimpleNamespace(index=0), SimpleNamespace(index=1), mornye])

    def test_confirm_switch_and_release_before_walk(self):
        task = self.task([(True,2,3),(True,0,3)])
        prepare_loot(task)
        self.assertEqual(task.executor.interaction.release_all.call_count,2)
        task.chars[2].switch_other_char.assert_called_once_with(allow_auto_combat=True)

    def test_failed_switch_stops_before_walking(self):
        task = self.task([(True,2,3),(True,2,3)])
        with self.assertRaises(RuntimeError): prepare_loot(task)

    def test_ambiguous_team_stops_before_switch(self):
        task = self.task([(True,0,2)])
        with self.assertRaises(RuntimeError): prepare_loot(task)
        task.chars[2].switch_other_char.assert_not_called()
