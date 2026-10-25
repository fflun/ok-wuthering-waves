"""Experimental browser capture/input adapter, isolated from the installed app."""
import asyncio
import base64
import threading
import time

import cv2
import numpy as np

from ok.device.capture_methods.base import BaseCaptureMethod
from ok.device.interaction_methods.browser import BrowserInteraction
from cloud_bridge import ChromeBridge, game_rect, pixel_crop
from cloud_cdp_input import BridgePage
from cloud_recovery import TransientFrameError, recover_frame


class CloudCapture(BaseCaptureMethod):
    name = "Cloud Wuwa browser screenshot"

    def __init__(self, config, exit_event):
        super().__init__()
        self.config = config
        self.exit_event = exit_event
        self._size = tuple(config.get('resolution', (1280, 720)))
        self.page = None
        self.hwnd = 0
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()
        def run_loop():
            asyncio.set_event_loop(self.loop)
            self.loop.call_soon(ready.set)
            self.loop.run_forever()
        self.loop_thread = threading.Thread(target=run_loop, daemon=True, name='CloudBridgeLoop')
        self.loop_thread.start()
        ready.wait(timeout=5)
        self._launch_lock = threading.Lock()
        self.block_input = True
        self.last_capture_ms = 0
        self.bridge = None
        self.recovering = False
        self._frame_lock = None

    def connected(self):
        return self.page is not None and not self.page.is_closed()

    def close(self):
        self.block_input = True
        if self.loop.is_closed():
            return
        try:
            self.run_in_loop(self._close_async())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop_thread.join(timeout=5)
            if self.loop_thread.is_alive():
                raise RuntimeError('Cloud bridge loop did not stop')
            self.loop.close()
            self.page = None

    def start_browser(self):
        with self._launch_lock:
            if not self.connected():
                self.run_in_loop(self._start_browser_async())

    async def _start_browser_async(self):
        if self.bridge is None:
            self.bridge = ChromeBridge()
            print('CLOUD_CONNECT 在云鸣潮连接器中点击连接当前游戏，无需配对码',flush=True)
        self.page = BridgePage(self)
        self._size = (1280, 720)
        self.block_input = True
        self.last_capture_ms = 0

    async def request(self, op, params=None):
        return await asyncio.to_thread(self.bridge.request,op,params)

    async def _close_async(self):
        self.block_input = True
        if self.bridge:
            try:
                if self.bridge.connected():
                    await self.request('release')
            finally:
                await asyncio.to_thread(self.bridge.close)
                self.bridge = None
        self.page = None

    def run_in_loop(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=60)
        except BaseException:
            future.cancel()
            raise

    async def metrics(self):
        return await self.request('metrics')

    async def game_rect(self):
        return game_rect(await self.metrics())

    async def frame(self):
        if self._frame_lock is None:
            self._frame_lock = asyncio.Lock()
        async with self._frame_lock:
            async def release():
                self.recovering = True
                await self.request('release')
                self.page.keyboard.held.clear()
                self.page.mouse.buttons.clear()
                await self.request('focus')
            try:
                return await recover_frame(self._read_frame, release,
                    lambda count: print(f'CLOUD_RECOVER frame retries={count}',flush=True), attempts=12)
            except BaseException:
                self.block_input = True
                raise
            finally:
                self.recovering = False

    async def _read_frame(self):
        before = await self.metrics()
        try:
            rect = game_rect(before)
        except (ValueError, RuntimeError) as exc:
            raise TransientFrameError(f'{exc}; source={before.get("source")}, rect={before.get("rect")}') from exc
        start = time.monotonic()
        try:
            result = await self.request('frame',{'clip':rect})
        except RuntimeError as exc:
            if str(exc) != '读取游戏视频帧失败；已停止输入':
                raise
            raise TransientFrameError(str(exc)) from exc
        if not result.get('gameSurface'):
            self.block_input = True
            raise RuntimeError('Reload cloud connector version 0.1.3 before this trial')
        if before.get('kind') == 'video' and not result.get('freshness'):
            raise RuntimeError('Reload cloud connector version 0.1.5 for fresh video frames')
        data = base64.b64decode(result['data'],validate=True)
        if result.get('format') != 'png' or not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Reload cloud connector version 0.1.6 for lossless frame transfer')
        after = await self.metrics()
        if (before['viewport'] != after.get('viewport') or
                before['rect'] != after.get('rect') or before['source'] != after.get('source')):
            raise TransientFrameError('Game layout changed during capture')
        self.last_capture_ms = round((time.monotonic()-start)*1000)
        decoded = cv2.imdecode(np.frombuffer(data,dtype=np.uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            raise RuntimeError('Screenshot decoding failed')
        layout_keys = ('ready','kind','rect','source','viewport','fit','position')
        if (list(decoded.shape[1::-1]) != before['source'] or
                any(result.get('metrics',{}).get(key) != before.get(key) for key in layout_keys)):
            raise TransientFrameError('Video frame does not match the measured game surface')
        return cv2.resize(decoded,(1280,720))

    def do_get_frame(self):
        if self.exit_event.is_set() or not self.connected():
            self.block_input = True
            return None
        try:
            return self.run_in_loop(self.frame())
        except Exception:
            self.block_input = True
            raise


class CloudInteraction(BrowserInteraction):
    def __init__(self, capture):
        super().__init__(capture)
        self.held_keys = set()
        self.held_buttons = set()

    def _run_action(self, coro):
        if self.capture.block_input:
            coro.close()
            raise RuntimeError('Cloud input stopped')
        return self.capture.run_in_loop(coro)

    async def point(self,x,y):
        r = await self.capture.game_rect()
        if not (0 <= x <= 1280 and 0 <= y <= 720):
            raise ValueError('Input coordinates outside game frame')
        return r['x']+x*r['width']/1280,r['y']+y*r['height']/720

    def send_key_down(self,key):
        self.held_keys.add(self._map_key(key))
        super().send_key_down(key)

    def send_key_up(self,key):
        super().send_key_up(key)
        self.held_keys.discard(self._map_key(key))

    def move(self,x,y):
        async def act():
            await self.capture.page.mouse.move(*await self.point(x,y))
        self._run_action(act())

    def click(self,x=-1,y=-1,move_back=False,name=None,down_time=.01,move=True,key='left'):
        async def act():
            if x >= 0 and y >= 0:
                await self.capture.page.mouse.move(*await self.point(x,y))
            self.held_buttons.add(key)
            try:
                await self.capture.page.mouse.down(button=key)
                await asyncio.sleep(down_time)
            finally:
                await self.capture.page.mouse.up(button=key)
                self.held_buttons.discard(key)
        self._run_action(act())

    def mouse_down(self,x=-1,y=-1,name=None,key='left'):
        async def act():
            if x >= 0 and y >= 0:
                await self.capture.page.mouse.move(*await self.point(x,y))
            self.held_buttons.add(key)
            await self.capture.page.mouse.down(button=key)
        self._run_action(act())

    def mouse_up(self,key='left'):
        async def act():
            await self.capture.page.mouse.up(button=key)
            self.held_buttons.discard(key)
        self._run_action(act())

    def scroll(self,x,y,scroll_amount):
        async def act():
            if x >= 0 and y >= 0:
                await self.capture.page.mouse.move(*await self.point(x,y))
            await self.capture.page.mouse.wheel(0,-100*scroll_amount)
        self._run_action(act())

    def swipe(self,x1,y1,x2,y2,duration,settle_time=0):
        async def act():
            await self.capture.page.mouse.move(*await self.point(x1,y1))
            self.held_buttons.add('left')
            try:
                await self.capture.page.mouse.down()
                steps=max(5,int(duration/20))
                for i in range(1,steps+1):
                    await self.capture.page.mouse.move(*await self.point(x1+(x2-x1)*i/steps,y1+(y2-y1)*i/steps))
                    await asyncio.sleep(duration/1000/steps)
                await asyncio.sleep(settle_time)
            finally:
                await self.capture.page.mouse.up()
                self.held_buttons.discard('left')
        self._run_action(act())

    def release_all(self):
        async def release():
            if self.capture.connected():
                await self.capture.request('release')
            if self.capture.page:
                self.capture.page.keyboard.held.clear()
                self.capture.page.mouse.buttons.clear()
            self.held_keys.clear()
            self.held_buttons.clear()
        self.capture.run_in_loop(release())
