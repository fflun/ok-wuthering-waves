"""Browser-only device backend. Current entry permits offline fixture mode only."""
from pathlib import Path
from cloud_daily_runtime import CloudCapture, CloudInteraction
from cloud_cdp_input import BridgePage


class LinuxPage(BridgePage):
    def is_closed(self):
        return not self.capture.connected()


class LinuxCapture(CloudCapture):
    def __init__(self, config, exit_event):
        if config.get('url', 'about:blank') != 'about:blank':
            raise ValueError('This offline entry may only open about:blank')
        self.browser_page = self.browser = self.context = self.playwright = self.cdp = None
        worker = (Path(__file__).parent/'chrome-extension/worker.js').read_text(encoding='utf-8')
        start = worker.index('function surfaceMetrics(')
        end = worker.index('\nasync function cdp(', start)
        # Share the tested video/canvas function; no page-screenshot fallback.
        self.surface_function = worker[start:end]
        self.blocked_requests = []
        super().__init__(config, exit_event)

    def connected(self):
        return self.browser_page is not None and not self.browser_page.is_closed()

    async def _start_browser_async(self):
        from playwright.async_api import async_playwright
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                executable_path=self.config.get('executable_path', '/usr/bin/chromium'),
                headless=True, chromium_sandbox=True,
                args=['--disable-background-networking','--no-first-run',
                      '--disable-component-update','--disable-sync','--disable-domain-reliability'])
            self.context = await self.browser.new_context(viewport={'width':1280,'height':720},
                device_scale_factor=1, offline=True, service_workers='block')
            async def reject(route):
                self.blocked_requests.append(route.request.url.split('?',1)[0])
                await route.abort()
            await self.context.route('**/*', reject)
            self.browser_page = await self.context.new_page()
            self.cdp = await self.context.new_cdp_session(self.browser_page)
            self.page = LinuxPage(self)
            self.block_input = True
        except BaseException:
            await self._close_async()
            raise

    async def request(self, op, params=None):
        params = params or {}
        if op == 'input':
            raise RuntimeError('Offline Linux device: input is disabled')
        if op == 'release':
            # No input is permitted in this phase; only clear local bookkeeping.
            if self.page:
                self.page.keyboard.held.clear()
                self.page.mouse.buttons.clear()
            return {}
        if not self.connected() or self.browser_page.url != 'about:blank':
            self.block_input = True
            raise RuntimeError('Offline page closed or navigated away')
        if op in ('metrics','frame'):
            if params.get('mode') == 'page':
                raise RuntimeError('Whole-page screenshots are not a cloud capture backend')
            return await self.browser_page.evaluate('('+self.surface_function+')', op == 'frame')
        if op == 'focus':
            return {}  # No host desktop focus changes in offline mode.
        raise ValueError('Unsupported offline operation: '+op)

    async def _close_async(self):
        self.block_input = True
        try:
            if self.browser:
                await self.browser.close()
        finally:
            try:
                if self.playwright:
                    await self.playwright.stop()
            finally:
                self.browser_page = self.browser = self.context = self.playwright = self.cdp = self.page = None


class LinuxBrowserDeviceManager:
    """Small real device contract for the original TaskExecutor, with no Win32 manager."""
    def __init__(self, exit_event, config=None):
        self.exit_event = exit_event
        self.config = {'preferred':'browser'}
        self.browser_config = dict(config or {})
        self.capture_method = self.interaction = self.executor = None
        self.hwnd_window = None
        self.device_dict = {}

    def update_browser_device(self):
        self.device_dict['browser'] = dict(device='browser',imei='browser',nick='Linux offline browser',
            address='about:blank',width=1280,height=720,resolution='1280x720',
            connected=bool(self.capture_method and self.capture_method.connected()))

    def get_preferred_device(self):
        return self.device_dict.get(self.config['preferred'])

    def get_resolution(self):
        return (1280,720)

    def update_resolution_for_hwnd(self):
        self.update_browser_device()  # Browser geometry, never a host window handle.

    def do_start(self, notify=True):
        if self.capture_method is None:
            self.capture_method = LinuxCapture(self.browser_config,self.exit_event)
            self.interaction = CloudInteraction(self.capture_method)
        try:
            self.capture_method.start_browser()
            self.update_browser_device()
        except BaseException:
            self.close()
            raise

    def stop_hwnd(self):
        self.close()

    def close(self):
        capture, self.capture_method = self.capture_method, None
        self.interaction = None
        if capture:
            capture.close()
        self.update_browser_device()
