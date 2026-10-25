"""Use the original OK capture/interaction contract with an owned headless browser."""
import asyncio
import time
from pathlib import Path

from cloud_background_browser import BackgroundBrowser
from cloud_cdp_input import BridgePage
from cloud_daily_runtime import CloudCapture
from cloud_background_startup import wait_fresh_surface, BackgroundFrameError, explicit_start_failure, dismiss_received_time_award


class BackgroundPage(BridgePage):
    def is_closed(self):
        return not self.capture.connected()


class BackgroundCapture(CloudCapture):
    def __init__(self,config,exit_event):
        self.driver=None
        self.sent_keys={}
        self.sent_buttons={}
        super().__init__(config,exit_event)

    def connected(self):
        return bool(self.driver and self.driver.page and not self.driver.page.is_closed())

    def run_in_loop(self,coro):
        future=asyncio.run_coroutine_threadsafe(coro,self.loop)
        try:
            return future.result(timeout=300)
        except BaseException:
            future.cancel()
            raise

    async def _start_browser_async(self):
        profile=Path(__file__).resolve().parent.parent/'okww-cloud-session/background/game-profile'
        account=self.config.get('account_id','a')
        if account!='a':
            from cloud_account_runtime import resolve_context
            paths,_=resolve_context(Path(__file__).resolve().parent,account)
            profile=paths.profile
        self.driver=BackgroundBrowser(profile,headless=True)
        try:
            self.block_input=True
            await self.driver.start()
            button=self.driver.page.get_by_role('button',name='进入游戏',exact=True)
            try:
                await button.click(timeout=10000)
                print('BACKGROUND_ENTER_CLICKED',flush=True)
            except Exception:
                if await dismiss_received_time_award(self.driver.page):
                    print('BACKGROUND_RECEIVED_TIME_AWARD_DISMISSED confirmed_frames=2 no_purchase',flush=True)
                    await button.click(timeout=10000)
                    print('BACKGROUND_ENTER_CLICKED',flush=True)
                elif not (await self.driver.metrics()).get('ready'):
                    await self.driver.page.screenshot(path=str(profile.parent/'background-start-page.png'))
                    raise RuntimeError('Enter game button unavailable; session needs attention')
            # Canvas is already supported by BackgroundBrowser.frame(). Do
            # not tear down a working cloud session just to force video.
            metrics=await wait_fresh_surface(self.driver,timeout=120)
            print(f'BACKGROUND_SURFACE_READY kind={metrics["kind"]} fresh_frames=2 input_disabled',flush=True)
            self.page=BackgroundPage(self)
            self.block_input=True
            self._loading_retry=0
        except BackgroundFrameError as exc:
            from cloud_autorun_state import write_json
            await self.driver.page.screenshot(path=str(profile.parent/'background-start-page.png'))
            text=await self.driver.page.locator('body').inner_text()
            start_failure=False
            if explicit_start_failure(text):
                await asyncio.sleep(.3)
                second=await self.driver.page.locator('body').inner_text()
                start_failure=explicit_start_failure(second)
                if start_failure:
                    await self.driver.page.screenshot(path=str(profile.parent/'background-start-confirmed.png'))
            retry=(getattr(self,'_loading_retry',0)==0
                   and exc.diagnostics.get('fresh_frames')==0
                   and exc.diagnostics.get('kind') is None
                   and exc.diagnostics.get('ready') is False
                   and ('游戏启动中' in text or start_failure)
                   and not any(word in text for word in ('登录','购买','支付','充值','时长不足')))
            exc.diagnostics['loading_screen']= '游戏启动中' in text
            exc.diagnostics['start_failure_dialog_confirmed']=start_failure
            exc.diagnostics['retry_allowed']=retry
            write_json(profile.parent/'background-start-diagnostics.json',exc.diagnostics)
            await self._close_async()
            if retry:
                self._loading_retry=1
                print('BACKGROUND_STARTUP_RETRY attempt=1/1 input_disabled reason='+
                      ('explicit_start_failure' if start_failure else 'loading'),flush=True)
                # Let the owned cloud client release before entering the same profile again.
                if start_failure:await asyncio.sleep(5)
                return await self._start_browser_async()
            raise
        except BaseException:
            await self._close_async()
            raise

    async def request(self,op,params=None):
        params=params or {}
        if op=='release':
            errors=[]
            for key,payload in list(self.sent_keys.items()):
                try:
                    await self.driver.cdp.send('Input.dispatchKeyEvent',{**payload,'type':'keyUp','modifiers':0,'text':''})
                    self.sent_keys.pop(key,None)
                except Exception as exc:errors.append(exc)
            for button,payload in list(self.sent_buttons.items()):
                try:
                    await self.driver.cdp.send('Input.dispatchMouseEvent',{**payload,'type':'mouseReleased','buttons':0})
                    self.sent_buttons.pop(button,None)
                except Exception as exc:errors.append(exc)
            if errors:raise RuntimeError('Background input release was not acknowledged') from errors[0]
            return {}
        self.driver.ensure_page()
        if op=='metrics':return await self.driver.metrics()
        if op=='frame':
            try:
                return await self.driver.frame()
            except Exception as exc:
                if not any(message in str(exc) for message in ('Video frame stalled','Canvas video stalled','Canvas frame stalled')):raise
                from cloud_recovery import TransientFrameError
                raise TransientFrameError('Background video frame stalled') from exc
        if op=='focus':
            # Internal page focus only; never restore or raise a Windows window.
            await self.driver.cdp.send('Emulation.setFocusEmulationEnabled',{'enabled':True})
            return {}
        if op!='input':raise ValueError('Unsupported background operation')
        method,payload=params['method'],params['params']
        if method=='Input.insertText':
            text=payload.get('text')
            if not isinstance(text,str) or len(text)>256:raise ValueError('Invalid game text')
            await self.driver.cdp.send(method,{'text':text})
        elif method=='Input.dispatchKeyEvent':
            key=payload['code']
            if payload['type']=='keyDown':self.sent_keys[key]=payload
            elif payload['type']!='keyUp':raise ValueError('Unsupported key action')
            await self.driver.cdp.send(method,payload)
            if payload['type']=='keyUp':self.sent_keys.pop(key,None)
        elif method=='Input.dispatchMouseEvent':
            button=payload.get('button')
            if payload['type']=='mousePressed':self.sent_buttons[button]=payload
            elif payload['type'] not in ('mouseReleased','mouseMoved','mouseWheel'):
                raise ValueError('Unsupported pointer action')
            await self.driver.cdp.send(method,payload)
            if payload['type']=='mouseReleased':self.sent_buttons.pop(button,None)
        else:raise ValueError('Unsupported background input method')
        return {}

    async def _close_async(self):
        self.block_input=True
        if self.driver:
            try:
                if self.driver.cdp:
                    await self.request('release')
            finally:
                await self.driver.close()
                self.driver=None
        self.page=None
