"""Owned Chromium session for background validation; never focuses host windows."""
import asyncio
import os
import sys
from pathlib import Path

GAME_URL = 'https://mc.kurogames.com/cloud/index.html'


class BackgroundBrowser:
    def __init__(self, profile, *, headless=True, synthetic=False):
        self.profile = Path(profile).resolve()
        self.headless = False if sys.platform == 'linux' and not synthetic else headless
        self.synthetic = synthetic
        self.playwright = self.context = self.page = self.cdp = None
        self.input_enabled = False
        self.keys = set()
        worker = (Path(__file__).parent/'chrome-extension/worker.js').read_text(encoding='utf-8')
        self.surface_function = worker[worker.index('function surfaceMetrics('):worker.index('\nasync function cdp(')]

    async def start(self):
        from playwright.async_api import async_playwright
        self.profile.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        try:
            attached = os.environ.get('OKWW_ATTACH_OWNED_SESSION') == '1' and not self.synthetic
            if attached:
                if sys.platform != 'linux':
                    raise RuntimeError('Owned session attachment is Linux-only')
                self.attached_browser = await self.playwright.chromium.connect_over_cdp('http://127.0.0.1:9229')
                contexts = self.attached_browser.contexts
                if len(contexts) != 1:
                    raise RuntimeError('Expected one owned browser context')
                self.context = contexts[0]
                pages = [p for p in self.context.pages if p.url.split('#',1)[0] == GAME_URL]
                if not pages:
                    raise RuntimeError('Owned cloud game tab missing; no navigation or login fallback')
                candidates=[]
                for existing in pages:
                    has_entry=await existing.get_by_role('button',name='\u8fdb\u5165\u6e38\u620f',exact=True).count()
                    surface=await existing.evaluate('('+self.surface_function+')(false)')
                    if has_entry == 1 or surface.get('ready'):
                        candidates.append(existing)
                if len(candidates) != 1:
                    raise RuntimeError('Expected exactly one authenticated entry/game tab; refusing tab-order guess')
                self.page = candidates[0]
                await self.page.set_viewport_size({'width':1280,'height':720})
            else:
                self.context = await self.playwright.chromium.launch_persistent_context(
                    str(self.profile), headless=self.headless, chromium_sandbox=True,
                    **({'executable_path': os.environ.get('OKWW_CHROMIUM', '/opt/cloudgames/browser/chromium-1243/chrome-linux64/chrome')} if sys.platform == 'linux' else {'channel':'chrome'}),
                    viewport={'width':1280,'height':720}, device_scale_factor=1,
                    args=(['--remote-debugging-address=127.0.0.1','--remote-debugging-port=9229'] if sys.platform == 'linux' and not self.synthetic else [])+['--enable-features=ThirdPartyStoragePartitioning','--no-first-run','--restore-last-session','--disable-background-timer-throttling',
                          '--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows',
                          '--mute-audio'],
                )
                restored=[p for p in self.context.pages if p.url.split('#',1)[0] == GAME_URL]
                candidates=[]
                for existing in restored:
                    await existing.wait_for_load_state('domcontentloaded',timeout=15000)
                    try:
                        await existing.get_by_role('button',name='\u8fdb\u5165\u6e38\u620f',exact=True).wait_for(state='visible',timeout=10000)
                        candidates.append(existing)
                    except Exception:
                        pass
                if len(candidates)>1:
                    raise RuntimeError('Multiple authenticated game tabs; selection requires attention')
                self.page = candidates[0] if candidates else (restored[0] if restored else (self.context.pages[0] if self.context.pages else await self.context.new_page()))
            # Cloud sessions may negotiate a WebGL canvas instead of video.
            # Preserve its rendered buffer for pixel reads between composites.
            await self.context.add_init_script("""(() => {
              if (location.origin !== 'https://mc.kurogames.com') return;
              const original = HTMLCanvasElement.prototype.getContext;
              HTMLCanvasElement.prototype.getContext = function(type, options) {
                if (['webgl','webgl2','experimental-webgl'].includes(type))
                  options = {...options, preserveDrawingBuffer:true};
                return original.call(this,type,options);
              };
            })();""")
            self.cdp = await self.context.new_cdp_session(self.page)
            # Page-level focus only. No bringToFront, window restore, SendInput or cursor changes.
            await self.cdp.send('Emulation.setFocusEmulationEnabled', {'enabled':True})
            if self.synthetic:
                await self.context.set_offline(True)
            elif not attached and self.page.url.split('#',1)[0] != GAME_URL:
                await self.page.goto(GAME_URL, wait_until='domcontentloaded', timeout=45000)
        except BaseException:
            await self.close()
            raise

    def ensure_page(self):
        if not self.page or self.page.is_closed():
            raise RuntimeError('Owned browser page is closed')
        expected = 'about:blank' if self.synthetic else GAME_URL
        if self.page.url.split('#',1)[0] != expected:
            self.input_enabled = False
            raise RuntimeError('Unexpected page; background input stopped')

    async def metrics(self):
        self.ensure_page()
        return await self.page.evaluate('('+self.surface_function+')(false)')

    async def frame(self):
        self.ensure_page()
        metrics=await self.metrics()
        if metrics.get('kind')=='canvas':
            return await asyncio.wait_for(self.page.evaluate("""async metrics => {
              const canvas=document.querySelector('#sr-canvas');
              if (!canvas) throw new Error('Canvas disappeared');
              let tap=window.__okwwCanvasTap;
              if (!tap || tap.canvas!==canvas) {
                if(tap) tap.stream.getTracks().forEach(t=>t.stop());
                const stream=canvas.captureStream(30), video=document.createElement('video');
                video.muted=true;video.playsInline=true;video.srcObject=stream;
                tap=window.__okwwCanvasTap={canvas,stream,video};
                await video.play();
              }
              return await new Promise((resolve,reject)=>{
                const timer=setTimeout(()=>{tap.video.cancelVideoFrameCallback(id);reject(new Error('Canvas video stalled'));},1500);
                const id=tap.video.requestVideoFrameCallback((now,meta)=>{
                  clearTimeout(timer);
                  try {
                    const output=tap.output || (tap.output=document.createElement('canvas'));
                    if(output.width!==metrics.source[0] || output.height!==metrics.source[1])
                      [output.width,output.height]=metrics.source;
                    output.getContext('2d').drawImage(tap.video,0,0);
                    resolve({data:output.toDataURL('image/png').split(',')[1],format:'png',gameSurface:true,metrics,
                      freshness:{mediaTime:meta.mediaTime,presentedFrames:meta.presentedFrames}});
                  } catch(e){reject(e);}
                });
              });
            }""",metrics),6)
        result = await asyncio.wait_for(self.page.evaluate('('+self.surface_function+')(true)'), 4)
        if result.get('metrics',{}).get('kind') == 'video' and not result.get('freshness'):
            raise RuntimeError('No fresh video frame')
        return result

    async def key(self, code, key, vk, down):
        self.ensure_page()
        if not self.input_enabled and down:
            raise RuntimeError('Background input is disabled')
        if down:
            self.keys.add((code,key,vk))
        await self.cdp.send('Input.dispatchKeyEvent', {
            'type':'keyDown' if down else 'keyUp','code':code,'key':key,
            'windowsVirtualKeyCode':vk,'text':''})
        if not down:
            self.keys.discard((code,key,vk))

    async def release(self):
        self.input_enabled = False
        for code,key,vk in list(self.keys):
            try:
                await self.key(code,key,vk,False)
            finally:
                self.keys.discard((code,key,vk))

    async def close(self):
        self.input_enabled = False
        try:
            if self.context:
                try:
                    await self.release()
                finally:
                    if os.environ.get('OKWW_ATTACH_OWNED_SESSION') == '1' and not self.synthetic:
                        pass  # release inputs and disconnect transport; retain user login session
                    elif self.cdp and not self.synthetic:
                        try:
                            await self.cdp.send('Browser.close')
                        except BaseException:
                            await self.context.close()
                            raise
                    else:
                        await self.context.close()
        finally:
            if self.playwright:
                await self.playwright.stop()
            self.context = self.page = self.cdp = self.playwright = None
