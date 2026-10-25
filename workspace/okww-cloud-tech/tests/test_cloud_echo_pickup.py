import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cloud_echo_pickup as pickup


class EchoPickupTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.actions = []
        self.held = set()
        self.clock = patch.object(pickup.time, 'monotonic', lambda: self.now)
        self.sleep = patch.object(pickup.time, 'sleep', self.advance)
        self.clock.start(); self.sleep.start()
        self.addCleanup(self.clock.stop); self.addCleanup(self.sleep.stop)

    def advance(self, seconds):
        self.now += seconds

    def task(self, *, prompt=False, echo=None):
        def observe():
            self.assertFalse(self.held, 'No held movement during image/OCR work')
            self.advance(.1)
        def down(key):
            self.assertLess(self.now, 10)
            self.actions.append(key); self.held.add(key)
        def up(key):self.held.discard(key)
        def release():self.held.clear()
        return SimpleNamespace(
            executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock(side_effect=release))),
            next_frame=observe, in_combat=lambda:False,
            find_f_with_text=Mock(return_value=prompt), absorb_echo_text=lambda:'ABSORB_ONLY',
            find_echos=Mock(return_value=[echo] if echo else []), yolo_threshold=.25,
            width_of_screen=lambda v:1280*v, height_of_screen=lambda v:720*v,
            send_key_down=down, send_key_up=up,
            middle_click=Mock(side_effect=lambda **k:self.advance(.05)),log_info=Mock())

    def echo(self, x=1000, y=350):
        return SimpleNamespace(center=lambda:(x,y),y=y,height=1)

    def test_walk_success_and_non_browser_never_start_fallback(self):
        for found,browser,mode,expected_calls in [(True,True,'Walk',0),(False,False,'Walk',0),
                                                (False,True,'Yolo',0),(False,True,'Walk',1)]:
            class Task:
                config={'Echo Pickup Method':mode}
                def walk_find_echo(self, **kw):return found
                def is_browser(self):return browser
            with patch.dict(sys.modules,{'src.task.FarmEchoTask':SimpleNamespace(FarmEchoTask=Task)}), patch.object(pickup,'search',return_value=True) as search:
                pickup.install(); installed=Task.walk_find_echo; pickup.install()
                self.assertIs(Task.walk_find_echo,installed)
                Task().walk_find_echo(time_out=3)
                self.assertEqual(search.call_count,expected_calls)

    def test_only_explicit_absorb_authorizes_f(self):
        task=self.task(prompt=True)
        self.assertTrue(pickup.search(task))
        self.assertEqual(self.actions,['f'])
        task.find_f_with_text.assert_called_once_with(target_text='ABSORB_ONLY')
        task.find_echos.assert_not_called()
        self.assertFalse(self.held)

    def test_directional_target_does_not_authorize_generic_f(self):
        for x,y,direction in [(1000,350,'d'),(200,350,'a'),(640,350,'w'),(640,600,'s')]:
            with self.subTest(direction=direction):
                self.now=0;self.actions=[]
                task=self.task(echo=self.echo(x,y))
                self.assertFalse(pickup.search(task))
                self.assertTrue(self.actions)
                self.assertEqual(set(self.actions),{direction})
                self.assertLessEqual(self.now,10.11)
                self.assertFalse(self.held)

    def test_late_absorb_ocr_cannot_send_f(self):
        task=self.task(prompt=True)
        def slow(**kw):self.advance(11);return True
        task.find_f_with_text.side_effect=slow
        self.assertFalse(pickup.search(task));self.assertEqual(self.actions,[])

    def test_late_detector_cannot_move(self):
        task=self.task()
        def slow(**kw):self.advance(11);return [self.echo()]
        task.find_echos.side_effect=slow
        self.assertFalse(pickup.search(task));self.assertEqual(self.actions,[])

    def test_resumed_combat_stops_search(self):
        task=self.task();task.in_combat=lambda:True
        self.assertFalse(pickup.search(task));self.assertEqual(self.actions,[])
        task.find_echos.assert_not_called()

    def test_no_target_has_bounded_sweeps(self):
        task=self.task()
        self.assertFalse(pickup.search(task))
        self.assertEqual(self.actions,['a']*4)
        self.assertEqual(task.middle_click.call_count,4)

    def test_failure_releases_input_and_propagates(self):
        task=self.task()
        def fail(key):self.held.add(key);raise RuntimeError('transport failed')
        task.send_key_down=fail
        with self.assertRaisesRegex(RuntimeError,'transport failed'):pickup.search(task)
        self.assertFalse(self.held)
        self.assertEqual(task.executor.interaction.release_all.call_count,2)


if __name__=='__main__':unittest.main()
