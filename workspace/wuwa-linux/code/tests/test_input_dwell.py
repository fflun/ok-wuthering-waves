import unittest,asyncio,time
from types import SimpleNamespace
from cloud_cdp_input import CdpKeyboard
from cloud_daily_runtime import CloudInteraction
class Tests(unittest.TestCase):
 def keyboard(self,delay):
  k=CdpKeyboard(None);events=[]
  async def down(key):events.append(('down',time.monotonic()))
  async def up(key):events.append(('up',time.monotonic()))
  k.down=down;k.up=up;asyncio.run(k.press('e',delay=delay));return events[1][1]-events[0][1]
 def test_short_key_survives_frame_sampling(self):self.assertGreaterEqual(self.keyboard(10),.05)
 def test_longer_key_not_shortened(self):self.assertGreaterEqual(self.keyboard(90),.085)
 def test_failed_down_still_releases(self):
  k=CdpKeyboard(None);released=[]
  async def down(key):raise RuntimeError('dispatch failed')
  async def up(key):released.append(key)
  k.down=down;k.up=up
  with self.assertRaises(RuntimeError):asyncio.run(k.press('e'))
  self.assertEqual(released,['e'])
 def test_short_mouse_click_dwell_and_release(self):
  events=[]
  class Mouse:
   async def down(self,button):events.append(('down',time.monotonic()))
   async def up(self,button):events.append(('up',time.monotonic()))
  capture=SimpleNamespace(block_input=False,page=SimpleNamespace(mouse=Mouse()),run_in_loop=asyncio.run)
  interaction=CloudInteraction(capture);interaction.click(down_time=.01)
  self.assertGreaterEqual(events[1][1]-events[0][1],.05);self.assertFalse(interaction.held_buttons)
if __name__=='__main__':unittest.main()
