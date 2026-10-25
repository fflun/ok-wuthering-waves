import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cloud_nest_pickup import NestPickup, PickupNotConfirmed, PickupSearchEmpty, PickupTargetNotReached
from cloud_nest_current import install
from cloud_nest_state import NestState, TARGET, KEY


def target(x=842, confidence=.252, y=28):
    return SimpleNamespace(x=x, y=y, width=410, height=498, confidence=confidence)


class PickupTests(unittest.TestCase):
    def test_authorized_unconfirmed_search_finishes_without_fake_absorption_or_repeat(self):
        task,pickup,finder=self.make()
        pickup._search=Mock(side_effect=PickupNotConfirmed('F sent; notification missed'))
        pickup.absorb_sent=True
        pickup.on_unconfirmed_allowed=Mock(return_value=True)
        self.assertFalse(pickup.collect())
        self.assertTrue(pickup.search_completed)
        self.assertFalse(pickup.confirmed)
        self.assertFalse(pickup.collect())
        pickup._search.assert_called_once()
        pickup.on_unconfirmed_allowed.assert_called_once_with(pickup)

    def test_unconfirmed_exception_still_stops_other_nests(self):
        task,pickup,finder=self.make()
        pickup._search=Mock(side_effect=PickupNotConfirmed('F sent; notification missed'))
        pickup.on_unconfirmed_allowed=Mock(return_value=False)
        with self.assertRaises(PickupNotConfirmed):pickup.collect()
        self.assertFalse(pickup.search_completed)

    def test_seen_target_can_use_native_circle_and_real_notification(self):
        task,pickup,finder=self.make()
        pickup.target_seen=True
        pickup._search=Mock(side_effect=PickupTargetNotReached('stable target not reached'))
        def circle():
            finder.return_value=True
            pickup.absorb()
        pickup.native_circle=Mock(side_effect=circle)
        pickup.return_to_same_nest=Mock()
        self.assertTrue(pickup.collect())
        pickup.native_circle.assert_called_once()
        pickup.return_to_same_nest.assert_not_called()
        self.assertTrue(pickup.confirmed)
        self.assertEqual([c.args[0] for c in task.send_key.call_args_list],['f'])

    def test_seen_target_without_notification_keeps_pending_not_empty(self):
        task,pickup,_=self.make()
        pickup.target_seen=True
        pickup._search=Mock(side_effect=PickupTargetNotReached('stable target not reached'))
        pickup.native_circle=Mock()
        pickup.return_to_same_nest=Mock()
        pickup.on_searched_empty=Mock()
        with self.assertRaises(PickupSearchEmpty):pickup.collect()
        pickup.native_circle.assert_called_once()
        pickup.return_to_same_nest.assert_called_once()
        pickup.on_searched_empty.assert_not_called()
        self.assertFalse(pickup.confirmed)

    def test_empty_search_is_a_separate_result_not_absorption(self):
        task,pickup,_=self.make()
        pickup._search=Mock(side_effect=PickupSearchEmpty('no target'))
        pickup.native_circle=Mock();pickup.return_to_same_nest=Mock();pickup.on_searched_empty=Mock()
        self.assertFalse(pickup.collect())
        self.assertTrue(pickup.search_completed);self.assertFalse(pickup.confirmed)
        pickup.on_searched_empty.assert_called_once();task.send_key.assert_not_called()

    def test_empty_result_disallowed_after_sent_f_or_seen_target(self):
        for flag in ('absorb_sent','target_seen'):
            task,pickup,_=self.make()
            setattr(pickup,flag,True)
            pickup._search=Mock(side_effect=PickupSearchEmpty('no target'))
            pickup.native_circle=Mock();pickup.return_to_same_nest=Mock();pickup.on_searched_empty=Mock()
            with self.assertRaises(PickupSearchEmpty):pickup.collect()
            pickup.on_searched_empty.assert_not_called();self.assertFalse(pickup.search_completed)

    def test_empty_callback_failure_keeps_pending(self):
        task,pickup,_=self.make()
        pickup._search=Mock(side_effect=PickupSearchEmpty('no target'))
        pickup.native_circle=Mock();pickup.return_to_same_nest=Mock()
        pickup.on_searched_empty=Mock(side_effect=RuntimeError('named count changed'))
        with self.assertRaisesRegex(RuntimeError,'named count changed'):pickup.collect()
        self.assertFalse(pickup.search_completed)
    def test_circle_search_precedes_teleport_and_requires_notification(self):
        task,pickup,_=self.make()
        order=[]
        pickup._search=Mock(side_effect=PickupSearchEmpty('no target'))
        pickup.return_to_same_nest=lambda:order.append('same_nest')
        def circle():
            order.append('circle');pickup.confirmed=True
        pickup.native_circle=circle
        self.assertTrue(pickup.collect());self.assertEqual(order,['circle'])
        task.executor.interaction.release_all.assert_called_once()

    def test_circle_return_value_alone_never_certifies_absorption(self):
        task,pickup,_=self.make()
        pickup._search=Mock(side_effect=PickupSearchEmpty('no target'))
        pickup.return_to_same_nest=Mock();pickup.native_circle=Mock(return_value=True)
        with self.assertRaisesRegex(PickupNotConfirmed,'without verified'):pickup.collect()
        pickup.native_circle.assert_called_once();self.assertFalse(pickup.confirmed)

    def test_in_place_circle_does_not_require_teleport(self):
        task,pickup,_=self.make()
        pickup._search=Mock(side_effect=PickupSearchEmpty('no target'))
        pickup.native_circle=Mock()
        with self.assertRaises(PickupNotConfirmed):pickup.collect()
        pickup.native_circle.assert_called_once()

    def test_native_approach_can_find_prompt_without_model(self):
        task,pickup,finder=self.make()
        pickup.native_approach=Mock(side_effect=lambda:setattr(finder,'return_value',True))
        self.assertTrue(pickup.collect())
        pickup.native_approach.assert_called_once()
        pickup._detect.assert_not_called()
        self.assertEqual([c.args[0] for c in task.send_key.call_args_list],['f'])

    def test_in_place_prompt_does_not_invoke_native_walk(self):
        task,pickup,_=self.make(prompt=True)
        pickup.native_approach=Mock()
        self.assertTrue(pickup.collect())
        pickup.native_approach.assert_not_called()

    def make(self, prompt=False, notification=True):
        task = SimpleNamespace(
            executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock())),
            ocr=Mock(return_value=[]), send_key=Mock(), next_frame=Mock(), sleep=Mock(),
            has_echo_notification=Mock(return_value=notification),
            wait_until=Mock(side_effect=lambda f, **kw: f()),
            turn_direction=Mock(), center_camera=Mock(), width_of_screen=lambda fraction: 1280*fraction,
            log_info=Mock(), _capture_success=True)
        finder = Mock(return_value=prompt)
        pickup = NestPickup(task, lambda: True, finder)
        pickup._detect = Mock(return_value=[])
        return task, pickup, finder

    def test_in_place_absorb_precedes_detection_or_movement(self):
        task, pickup, _ = self.make(prompt=True)
        self.assertTrue(pickup.collect())
        self.assertEqual([c.args[0] for c in task.send_key.call_args_list], ['f'])
        pickup._detect.assert_not_called()
        task.turn_direction.assert_not_called()
        self.assertTrue(pickup.confirmed)
        self.assertFalse(task._capture_success)  # old flag was cleared before verification

    def test_ocr_fallback_still_requires_exact_unique_prompt(self):
        task, pickup, _ = self.make()
        task.ocr.return_value = [SimpleNamespace(name='吸收')]
        self.assertTrue(pickup.collect())
        self.assertEqual(task.send_key.call_args.args[0], 'f')
        pickup._detect.assert_not_called()

    def test_two_frames_allow_short_step_then_absorb(self):
        task, pickup, finder = self.make()
        pickup._detect.return_value = [target()]
        task.send_key.side_effect = lambda key, **kw: setattr(finder, 'return_value', True) if key == 'd' else None
        self.assertTrue(pickup.collect())
        self.assertEqual([c.args[0] for c in task.send_key.call_args_list], ['d', 'f'])
        self.assertEqual(pickup._detect.call_count, 2)
        self.assertEqual(task.send_key.call_args_list[0].kwargs['down_time'], .18)

    def test_transient_or_moving_false_positive_never_causes_approach(self):
        for second in ([], [target(x=0)]):
            task, pickup, _ = self.make()
            pickup._detect.side_effect = [[target()], second]*4
            with self.assertRaisesRegex(RuntimeError, 'bounded search'):
                pickup.collect()
            task.send_key.assert_not_called()
            self.assertEqual(task.turn_direction.call_count, 3)
            self.assertFalse(pickup.confirmed)

    def test_lost_target_stops_forward_steps(self):
        task, pickup, _ = self.make()
        pickup._detect.side_effect = [[target(x=435)], [target(x=435)]] + [[]]*8
        with self.assertRaises(RuntimeError):
            pickup.collect()
        self.assertEqual([c.args[0] for c in task.send_key.call_args_list], ['w'])

    def test_input_exception_releases_all_and_stops(self):
        task, pickup, _ = self.make()
        pickup._detect.return_value = [target()]
        task.send_key.side_effect = RuntimeError('input failed')
        with self.assertRaisesRegex(RuntimeError, 'input failed'):
            pickup.collect()
        self.assertGreaterEqual(task.executor.interaction.release_all.call_count, 2)
        task.turn_direction.assert_not_called()

    def test_no_notification_does_not_trigger_wandering_or_false_success(self):
        task, pickup, _ = self.make(prompt=True, notification=False)
        with self.assertRaisesRegex(RuntimeError, 'notification not verified'):
            pickup.collect()
        self.assertFalse(pickup.confirmed)
        self.assertFalse(task._capture_success)
        self.assertEqual(task.send_key.call_count, 2)
        pickup._detect.assert_not_called()
        task.turn_direction.assert_not_called()

    def test_disappeared_prompt_can_confirm_late_without_second_f(self):
        task,pickup,_=self.make(notification=False)
        pickup.prompt=Mock(side_effect=[True,True,False])
        task.wait_until=Mock(side_effect=[False,True])
        pickup.on_confirmed=Mock()
        self.assertTrue(pickup.absorb())
        self.assertTrue(pickup.confirmed)
        self.assertTrue(pickup.search_completed)
        pickup.on_confirmed.assert_called_once()
        self.assertEqual(task.send_key.call_count,1)
        self.assertEqual([c.kwargs['time_out'] for c in task.wait_until.call_args_list],[5,15])

    def test_disappeared_prompt_without_native_notification_still_stops(self):
        task,pickup,_=self.make(notification=False)
        pickup.prompt=Mock(side_effect=[True,True,False])
        pickup.on_confirmed=Mock()
        with self.assertRaises(PickupNotConfirmed):pickup.absorb()
        self.assertFalse(pickup.confirmed)
        self.assertFalse(pickup.search_completed)
        pickup.on_confirmed.assert_not_called()
        self.assertEqual(task.send_key.call_count,1)
        self.assertEqual([c.kwargs['time_out'] for c in task.wait_until.call_args_list],[5,15])

    def test_unfinished_combat_refuses_pickup(self):
        task, pickup, _ = self.make(prompt=True)
        pickup.complete = lambda: False
        with self.assertRaisesRegex(RuntimeError, 'requires verified'):
            pickup.collect()
        task.send_key.assert_not_called()
        pickup._detect.assert_not_called()

    def test_approach_is_bounded_without_prompt(self):
        task, pickup, _ = self.make()
        pickup._detect.return_value = [target()]
        with patch('cloud_nest_pickup.time.monotonic', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'bounded search'):
                pickup.collect()
        self.assertEqual(task.send_key.call_count, 30)
        self.assertFalse(pickup.confirmed)
        self.assertTrue(all(c.args[0] == 'd' for c in task.send_key.call_args_list))

    def test_elapsed_deadline_prevents_approach(self):
        task, pickup, _ = self.make()
        pickup._detect.return_value = [target()]
        with patch('cloud_nest_pickup.time.monotonic', side_effect=[0, 31, 31]):
            with self.assertRaisesRegex(RuntimeError, 'bounded search'):
                pickup.collect()
        task.send_key.assert_not_called()
        pickup._detect.assert_not_called()

    def test_current_nest_entry_uses_pickup_and_restores_hooks(self):
        import numpy as np
        for notification in (True, False):
            task, _, finder = self.make(prompt=True, notification=notification)
            originals = {name: Mock() for name in ('in_combat', 'combat_end_condition',
                         'combat_once', 'pick_f', 'pick_echo', 'walk_find_echo', 'run_until')}
            for name, method in originals.items():
                setattr(task, name, method)
            task.find_f_with_text = finder
            task.ocr.return_value = [SimpleNamespace(name='123456789')]
            task.info = {}
            task.ensure_main = Mock()
            task.load_chars = Mock()
            task.reset_to_false = Mock()
            task.click = Mock()
            task.width_of_screen = lambda f: 1280*f
            task._travel_to_nest_or_skip = Mock(return_value=True)
            task.frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            stub = SimpleNamespace(WWOneTimeTask=SimpleNamespace(run=Mock()))
            box = SimpleNamespace(name='41/41',x=680,y=350,width=40,height=20)
            with tempfile.TemporaryDirectory() as directory, \
                    patch.dict('sys.modules', {'src.task.WWOneTimeTask': stub,
                        'src.task.NightmareNestTask': SimpleNamespace(NestTarget=lambda box,key: SimpleNamespace(box=box,cache_key=key))}), \
                    patch('cloud_nest_entry.select', return_value=(box,KEY,TARGET,(41,41),(41,41))), \
                    patch('cloud_nest_current.NestState', side_effect=lambda path,account,**kw: NestState(Path(directory)/'state.json',account,**kw)), \
                    patch('cloud_nest_current.time.monotonic', side_effect=range(100)):
                install(task, Path(directory))
                if notification:
                    task.run()
                    self.assertTrue(task.info['Nest Echo Collected'])
                else:
                    with self.assertRaisesRegex(RuntimeError, 'notification not verified'):
                        task.run()
                for name, method in originals.items():
                    self.assertIs(getattr(task, name), method)
                self.assertIs(task.find_f_with_text, finder)
                originals['combat_once'].assert_not_called()
                originals['walk_find_echo'].assert_not_called()
                self.assertEqual([c.args[0] for c in task.send_key.call_args_list], ['f']*(1 if notification else 2))

    def test_notification_retry_needs_fresh_prompt(self):
        task,pickup,finder=self.make(prompt=True,notification=False)
        finder.side_effect=[True,True,False]
        with self.assertRaisesRegex(RuntimeError,'notification not verified'):pickup.collect()
        self.assertEqual(task.send_key.call_count,1)

    def test_ambiguous_f_stops_before_return_or_another_use(self):
        task,pickup,_=self.make(prompt=True,notification=False)
        pickup.return_to_same_nest=Mock(side_effect=lambda:setattr(task.has_echo_notification,'return_value',True))
        with self.assertRaisesRegex(PickupNotConfirmed,'notification not verified'):pickup.collect()
        pickup.return_to_same_nest.assert_not_called()
        self.assertEqual(task.send_key.call_count,2)

    def test_return_is_bounded_and_never_proves_pickup(self):
        task,pickup,_=self.make(prompt=True,notification=False)
        pickup.return_to_same_nest=Mock()
        with self.assertRaisesRegex(RuntimeError,'notification not verified'):pickup.collect()
        pickup.return_to_same_nest.assert_not_called()
        self.assertFalse(pickup.confirmed)

    def test_yolo_gets_own_budget_after_native_walk(self):
        task,pickup,_=self.make()
        clock=[0]
        pickup.native_approach=Mock(side_effect=lambda:clock.__setitem__(0,60))
        with patch('cloud_nest_pickup.time.monotonic',side_effect=lambda:clock[0]):
            with self.assertRaisesRegex(RuntimeError,'bounded search'):pickup.collect()
        self.assertGreater(pickup._detect.call_count,0)

    def test_yolo_deadline_blocks_late_absorb_input(self):
        task,pickup,_=self.make(prompt=True)
        with patch('cloud_nest_pickup.time.monotonic',return_value=11):
            self.assertFalse(pickup.absorb(input_deadline=10))
        task.send_key.assert_not_called()
