import asyncio
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch


class LinuxDeviceTests(unittest.TestCase):
    def test_default_entry_does_not_import_runtime(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,'-I',str(root/'main_cloud_linux.py')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('LINUX_OFFLINE',result.stdout)

    def test_game_urls_rejected_before_starting_loop_or_browser(self):
        from cloud_linux_device import LinuxCapture
        for url in ('https://mc.kurogames.com/cloud/index.html','file:///tmp/x','data:text/html,test'):
            with self.assertRaises(ValueError): LinuxCapture({'url':url},threading.Event())

    def test_backend_rejects_input_even_if_flag_were_cleared(self):
        from cloud_linux_device import LinuxCapture
        capture=object.__new__(LinuxCapture)
        capture.block_input=False
        with self.assertRaisesRegex(RuntimeError,'input is disabled'):
            asyncio.run(capture.request('input',{'method':'Input.dispatchKeyEvent'}))

    def test_failed_start_cleans_up_owned_capture(self):
        from cloud_linux_device import LinuxBrowserDeviceManager
        capture=Mock()
        capture.start_browser.side_effect=RuntimeError('launch failed')
        with patch('cloud_linux_device.LinuxCapture',return_value=capture), patch('cloud_linux_device.CloudInteraction'):
            manager=LinuxBrowserDeviceManager(threading.Event())
            with self.assertRaisesRegex(RuntimeError,'launch failed'): manager.do_start()
            capture.close.assert_called_once()
            self.assertIsNone(manager.capture_method)
            self.assertFalse(manager.get_preferred_device()['connected'])


if __name__ == '__main__': unittest.main()
