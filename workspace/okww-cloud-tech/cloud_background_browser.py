"""Owned Chromium session for background validation; never focuses host windows."""
import asyncio
from pathlib import Path

GAME_URL = 'https://mc.kurogames.com/cloud/index.html'


class BackgroundBrowser:
    def __init__(self, profile, *, headless=True, synthetic=False):
        self.profile = Path(profile).resolve()
        self.headless = headless
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
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(self.profile), channel='chrome', headless=self.headless,
                viewport={'width':1280,'height':720}, device_scale_factor=1,
                args=['--no-first-run','--disable-background-timer-throttling',
                      '--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows',
                      '--mute-audio'],
            )
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
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
            else:
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
                    const output=document.createElement('canvas');
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
                    await self.context.close()
        finally:
            if self.playwright:
                await self.playwright.stop()
            self.context = self.page = self.cdp = self.playwright = None
