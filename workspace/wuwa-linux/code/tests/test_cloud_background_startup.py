import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from cloud_background_startup import BackgroundFrameError, wait_fresh_surface, explicit_start_failure


def frame(kind='video', time=1, count=1):
    return dict(gameSurface=True, data='fixture-pixels',
                metrics=dict(ready=True, kind=kind, source=[1280,720]),
                freshness=dict(mediaTime=time, presentedFrames=count))


class Clock:
    def __init__(self): self.value=0
    def __call__(self): return self.value
    async def sleep(self, seconds): self.value+=seconds


class BackgroundStartupTests(unittest.IsolatedAsyncioTestCase):
    def browser(self, frames):
        return SimpleNamespace(metrics=AsyncMock(return_value=dict(ready=True,kind='canvas')),
                               frame=AsyncMock(side_effect=frames), close=AsyncMock(),
                               cdp=SimpleNamespace(send=AsyncMock()))

    async def wait(self, browser, timeout=1):
        clock=Clock()
        return await wait_fresh_surface(browser,timeout=timeout,clock=clock,pause=clock.sleep)

    async def test_canvas_handoff_retains_session_with_two_fresh_frames(self):
        browser=self.browser([frame('canvas',1,1),frame('canvas',2,2)])
        result=await self.wait(browser)
        self.assertEqual(result['kind'],'canvas')
        browser.close.assert_not_awaited();browser.cdp.send.assert_not_awaited()

    async def test_video_remains_supported(self):
        browser=self.browser([frame(),frame(time=2,count=2)])
        self.assertEqual((await self.wait(browser))['kind'],'video')

    async def test_stale_frames_never_enable_readiness(self):
        browser=self.browser(None);browser.frame=AsyncMock(return_value=frame())
        with self.assertRaises(BackgroundFrameError):await self.wait(browser)
        browser.close.assert_not_awaited()

    async def test_ready_canvas_without_freshness_is_rejected(self):
        value=frame('canvas');value.pop('freshness')
        browser=self.browser(None);browser.frame=AsyncMock(return_value=value)
        with self.assertRaises(BackgroundFrameError):await self.wait(browser)

    async def test_loading_canvas_stall_retries_same_session(self):
        browser=self.browser([RuntimeError('Canvas video stalled'),frame('canvas',1,1),frame('canvas',2,2)])
        self.assertEqual((await self.wait(browser))['kind'],'canvas')
        browser.close.assert_not_awaited()

    async def test_transport_change_needs_a_new_pair(self):
        browser=self.browser([frame('video',1,1),frame('canvas',2,2),frame('canvas',3,3)])
        self.assertEqual((await self.wait(browser))['kind'],'canvas')
        self.assertEqual(browser.frame.await_count,3)

    async def test_browser_wrapped_canvas_stall_waits_for_new_pair(self):
        error=Exception('Page.evaluate: Error: Canvas video stalled\n    at eval (fixture)')
        browser=self.browser([frame('canvas',1,1),error,frame('canvas',2,2),frame('canvas',3,3)])
        self.assertEqual((await self.wait(browser))['kind'],'canvas')
        self.assertEqual(browser.frame.await_count,4)
        browser.close.assert_not_awaited();browser.cdp.send.assert_not_awaited()

    async def test_browser_wrapped_persistent_stall_times_out(self):
        browser=self.browser(None)
        browser.frame=AsyncMock(side_effect=Exception('Page.evaluate: Error: Canvas video stalled'))
        with self.assertRaises(BackgroundFrameError) as raised:await self.wait(browser)
        self.assertGreater(raised.exception.diagnostics['frame_stalls'],0)
        self.assertEqual(raised.exception.diagnostics['fresh_frames'],0)
        browser.cdp.send.assert_not_awaited();browser.close.assert_not_awaited()

    async def test_unrelated_browser_errors_stop_immediately(self):
        for message in ('Page.evaluate: Error: Unexpected page; background input stopped',
                        'Page.evaluate: Error: Login stalled', 'Target page, context or browser has been closed'):
            browser=self.browser([Exception(message)])
            with self.assertRaisesRegex(Exception,message):await self.wait(browser)
            self.assertEqual(browser.frame.await_count,1)

    async def test_forbidden_navigation_error_is_not_hidden(self):
        browser=self.browser([RuntimeError('Unexpected page; background input stopped')])
        with self.assertRaisesRegex(RuntimeError,'Unexpected page'):await self.wait(browser)

    async def test_actual_startup_method_does_not_relaunch_canvas_session(self):
        # Exercise the real method without loading native game frameworks.
        source=Path(__file__).resolve().parents[1]/'cloud_background_runtime.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BackgroundCapture')
        method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_start_browser_async')
        browser=self.browser([frame('canvas',1,1),frame('canvas',2,2)])
        browser.start=AsyncMock()
        browser.page=Mock();browser.page.get_by_role.return_value.click=AsyncMock()
        factory=Mock(return_value=browser)
        obj=SimpleNamespace(config={},block_input=False,_close_async=AsyncMock())
        namespace=dict(__file__=str(source),Path=Path,BackgroundBrowser=factory,
                       BackgroundPage=lambda capture:'connected',wait_fresh_surface=wait_fresh_surface,
                       BackgroundFrameError=BackgroundFrameError,explicit_start_failure=explicit_start_failure,
                       asyncio=__import__('asyncio'))
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),namespace)
        await namespace['_start_browser_async'](obj)
        factory.assert_called_once();browser.start.assert_awaited_once()
        browser.close.assert_not_awaited();obj._close_async.assert_not_awaited()
        self.assertTrue(obj.block_input);self.assertEqual(obj.page,'connected')

    async def startup_failure(self, text, failures):
        import sys
        from unittest.mock import patch
        source=Path(__file__).resolve().parents[1]/'cloud_background_runtime.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BackgroundCapture')
        method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_start_browser_async')
        browser=self.browser(None);browser.start=AsyncMock()
        browser.page=Mock();browser.page.get_by_role.return_value.click=AsyncMock()
        browser.page.screenshot=AsyncMock()
        browser.page.locator.return_value.inner_text=AsyncMock(return_value=text)
        factory=Mock(return_value=browser);saved=Mock()
        wait=AsyncMock(side_effect=failures)
        obj=SimpleNamespace(config={},block_input=False,_close_async=AsyncMock())
        namespace=dict(__file__=str(source),Path=Path,BackgroundBrowser=factory,
                       BackgroundPage=lambda capture:'connected',wait_fresh_surface=wait,
                       BackgroundFrameError=BackgroundFrameError,explicit_start_failure=explicit_start_failure,
                       asyncio=SimpleNamespace(sleep=AsyncMock()))
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),namespace)
        async def run():return await namespace['_start_browser_async'](obj)
        obj._start_browser_async=run
        with patch.dict(sys.modules,{'cloud_autorun_state':SimpleNamespace(write_json=saved)}):
            try:await run()
            except BackgroundFrameError:pass
        return obj,factory,saved,browser

    def empty_surface_failure(self):
        return BackgroundFrameError(dict(ready=False,kind=None,fresh_frames=0,frame_stalls=0))

    async def test_loading_timeout_retries_once_then_requires_fresh_frames(self):
        obj,factory,saved,browser=await self.startup_failure('游戏启动中，请耐心等待~',
            [self.empty_surface_failure(),dict(kind='video')])
        self.assertEqual(factory.call_count,2)
        obj._close_async.assert_awaited_once()
        self.assertTrue(obj.block_input);self.assertEqual(obj.page,'connected')
        browser.cdp.send.assert_not_awaited()
        self.assertTrue(saved.call_args.args[1]['retry_allowed'])

    async def test_loading_retry_exhaustion_stops_without_game_input(self):
        obj,factory,saved,browser=await self.startup_failure('游戏启动中',
            [self.empty_surface_failure(),self.empty_surface_failure()])
        self.assertEqual(factory.call_count,2);self.assertFalse(hasattr(obj,'page'))
        self.assertFalse(saved.call_args.args[1]['retry_allowed'])
        browser.cdp.send.assert_not_awaited()

    async def test_login_or_purchase_and_nonloading_do_not_retry(self):
        for text in ('游戏启动中，请登录','游戏启动中，时长不足请充值','连接失败'):
            obj,factory,saved,browser=await self.startup_failure(text,[self.empty_surface_failure()])
            self.assertEqual(factory.call_count,1)
            self.assertFalse(saved.call_args.args[1]['retry_allowed'])
            self.assertTrue(obj.block_input);browser.cdp.send.assert_not_awaited()


    async def test_explicit_start_failure_reconnects_once_without_game_input(self):
        text='提示\n开始游戏失败，请稍后重试，若仍无法解决请重启客户端或寻求客服支持。\n好的'
        obj,factory,saved,browser=await self.startup_failure(text,
            [self.empty_surface_failure(),dict(kind='video')])
        self.assertEqual(factory.call_count,2)
        self.assertTrue(saved.call_args.args[1]['start_failure_dialog_confirmed'])
        self.assertTrue(obj.block_input)
        browser.cdp.send.assert_not_awaited()
        self.assertGreaterEqual(browser.page.locator.return_value.inner_text.await_count,2)

    async def test_explicit_start_failure_exhaustion_stops(self):
        text='提示\n开始游戏失败，请稍后重试，若仍无法解决请重启客户端或寻求客服支持。\n好的'
        obj,factory,saved,browser=await self.startup_failure(text,
            [self.empty_surface_failure(),self.empty_surface_failure()])
        self.assertEqual(factory.call_count,2)
        self.assertFalse(saved.call_args.args[1]['retry_allowed'])
        self.assertFalse(hasattr(obj,'page'))

    def test_explicit_start_failure_never_accepts_login_resource_or_vague_error(self):
        text='提示 开始游戏失败，请稍后重试，若仍无法解决请重启客户端或寻求客服支持。 好的'
        self.assertTrue(explicit_start_failure(text))
        for extra in ('登录','购买','支付','充值','时长不足'):
            self.assertFalse(explicit_start_failure(text+extra))
        self.assertFalse(explicit_start_failure('提示 开始游戏失败 好的'))

if __name__=='__main__':unittest.main()
