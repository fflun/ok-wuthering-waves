"""OS boundaries; browser tasks must never move the host desktop cursor."""
from contextlib import contextmanager
import os
import sys


def desktop_cursor_available():
    return sys.platform == 'win32'


def _desktop_api():
    if not desktop_cursor_available():
        raise RuntimeError('Native desktop cursor control is Windows-only; use browser input')
    import win32api
    return win32api


def get_desktop_cursor():
    return _desktop_api().GetCursorPos()


def set_desktop_cursor(position):
    _desktop_api().SetCursorPos(position)


@contextmanager
def wheel_cursor(task, x, y):
    if task.is_browser():
        task.move(x, y)
        yield
        return
    api = _desktop_api()
    previous = api.GetCursorPos()
    try:
        task.move(x, y)
        api.SetCursorPos(task.executor.interaction.capture.get_abs_cords(x, y))
        yield
    finally:
        api.SetCursorPos(previous)


def reveal_output_folder(path):
    """Desktop convenience is optional on the server; never spawn a file manager."""
    if sys.platform != 'win32':
        return False
    os.startfile(os.path.abspath(path))
    return True
