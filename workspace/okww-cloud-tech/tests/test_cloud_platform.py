import ast
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from src import platform_io


class PlatformTests(unittest.TestCase):
    def test_browser_wheel_never_touches_desktop(self):
        task=SimpleNamespace(is_browser=lambda:True,move=Mock())
        with patch.object(platform_io,'_desktop_api',side_effect=AssertionError('Desktop used')):
            with platform_io.wheel_cursor(task,100,200): pass
        task.move.assert_called_once_with(100,200)

    def test_native_cursor_restores_even_on_exception(self):
        api=Mock(); api.GetCursorPos.return_value=(11,22)
        capture=Mock(); capture.get_abs_cords.return_value=(101,202)
        task=SimpleNamespace(is_browser=lambda:False,move=Mock(),executor=SimpleNamespace(interaction=SimpleNamespace(capture=capture)))
        with patch.object(platform_io,'_desktop_api',return_value=api):
            with self.assertRaises(ValueError):
                with platform_io.wheel_cursor(task,100,200): raise ValueError('cancel')
        self.assertEqual([call.args[0] for call in api.SetCursorPos.call_args_list],[(101,202),(11,22)])

    def test_linux_native_cursor_rejected_before_import(self):
        with patch.object(platform_io.sys,'platform','linux'):
            self.assertFalse(platform_io.desktop_cursor_available())
            with self.assertRaisesRegex(RuntimeError,'Windows-only'): platform_io.get_desktop_cursor()
            self.assertFalse(platform_io.reveal_output_folder('screenshots'))

    def test_linux_mouse_reset_does_not_schedule(self):
        source=Path('src/task/MouseResetTask.py').read_text(encoding='utf-8')
        cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef))
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        namespace={'desktop_cursor_available':lambda:False,'logger':Mock()}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<native run>','exec'),namespace)
        task=SimpleNamespace(enabled=True,is_browser=lambda:False,post_mouse_reset=Mock())
        namespace['run'](task)
        task.post_mouse_reset.assert_not_called()

    def test_capture_lifecycle_has_no_bridge_or_browser(self):
        from cloud_daily_runtime import CloudCapture
        with patch('cloud_daily_runtime.ChromeBridge',side_effect=AssertionError('Bridge started')):
            capture=CloudCapture({'resolution':(1280,720)},threading.Event())
            self.assertFalse(capture.connected())
            self.assertIsNone(capture.bridge)
            self.assertIsNone(capture.do_get_frame())
            capture.close()
            capture.close()
            self.assertFalse(capture.loop_thread.is_alive())
            self.assertTrue(capture.loop.is_closed())

if __name__=='__main__': unittest.main()
