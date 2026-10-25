"""Parent-owned browser lifetime; native task children attach without reconnecting."""
import asyncio,json,os,signal,subprocess,sys,time,uuid
from pathlib import Path

def validate_ready(record, token, pid, started):
    if (record.get('token')!=token or record.get('pid')!=pid
            or record.get('at',0)<started or record.get('status')!='READY'
            or record.get('capture_compatible') is not True
            or record.get('fresh_capture_verified') is not True
            or record.get('recognizer_resolution')!=[1280,720]):
        raise RuntimeError('Cloud session readiness is stale, foreign, or unverified')
    return record

class OwnedSession:
    def __init__(self,output,state):
        self.state=Path(state);self.token=uuid.uuid4().hex
        self.output=Path(output)/('session-'+self.token)
        self.child=None;self.log=None
    def start(self,boundary):
        self.output.mkdir()
        self.started=time.time()
        self.log=(self.output/'run.log').open('w')
        env=dict(os.environ);env.pop('OKWW_ATTACH_OWNED_SESSION',None)
        self.child=subprocess.Popen([sys.executable,'-u',__file__,'--host',str(self.output),self.token,str(os.getpid())],
            env=env,stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            boundary()
            if self.child.poll() is not None:raise RuntimeError('Owned cloud startup failed; see '+str(self.output))
            ready=self.output/'ready.json'
            if ready.exists():return validate_ready(json.loads(ready.read_text()),self.token,self.child.pid,self.started)
            time.sleep(1)
        raise RuntimeError('Owned cloud startup exceeded 300 seconds')
    def assert_alive(self):
        if self.child is None or self.child.poll() is not None:
            raise RuntimeError('Parent-owned cloud session exited')
    def close(self):
        if self.child is not None and self.child.poll() is None:
            (self.output/'stop').touch()
            try:self.child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(self.child.pid,signal.SIGTERM)
                try:self.child.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(self.child.pid,signal.SIGKILL);self.child.wait()
        if self.log:self.log.close()

async def host(output,token,parent):
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from cloud_background_browser import BackgroundBrowser
    from cloud_background_startup import wait_fresh_surface,dismiss_received_time_award
    from cloud_stream_profile import configure_stream
    from cloud_compositor_lease import CompositorLease,verify_fresh_capture
    from cloud_autorun_state import day_key,write_json
    state=Path('/opt/cloudgames/wuwa-20261023/okww-cloud-session/background')
    assert os.getppid()==parent,'Only the locked workflow parent may own this session'
    driver=BackgroundBrowser(state/'game-profile')
    day=day_key();began=time.monotonic();lease=None
    try:
        await driver.start()
        if await dismiss_received_time_award(driver.page):
            await driver.page.locator('.award').wait_for(state='hidden',timeout=5000)
        entry=driver.page.get_by_role('button',name='进入游戏',exact=True)
        await entry.wait_for(state='visible',timeout=20000)
        try:
            await entry.click(timeout=5000)
        except PlaywrightTimeoutError:
            # This receipt can arrive after the entry button becomes visible.
            # Retry once only after the exact verified overlay is dismissed.
            if not await dismiss_received_time_award(driver.page):
                raise
            await driver.page.locator('.award').wait_for(state='hidden',timeout=5000)
            await entry.click(timeout=10000)
        # Observe the SAME connection, with inputs disabled, before the original
        # ultra/60 profile checks. Never reload, hide a modal, or send gameplay input.
        loading=driver.page.get_by_text('游戏启动中，请耐心等待~',exact=True)
        await wait_fresh_surface(driver,timeout=120)
        await loading.wait_for(state='hidden',timeout=max(1,int((240-(time.monotonic()-began))*1000)))
        await wait_fresh_surface(driver,timeout=20)
        profile=await configure_stream(driver)
        lease=CompositorLease(driver.cdp)
        await lease.start()
        capture=await verify_fresh_capture(driver)
        lease.assert_healthy()
        write_json(output/'fresh-capture.json',capture)
        write_json(output/'ready.json',dict(status='READY',token=token,pid=os.getpid(),at=time.time(),
            fresh_capture_verified=True,native_720p=profile['native_720p'],capture_compatible=profile['capture_compatible'],
            recognizer_resolution=profile['recognizer_resolution'],source=profile['samples'][-1]['metrics']['source'],input_enabled=False))
        while not (output/'stop').exists():
            lease.assert_healthy()
            if os.getppid()!=parent or day_key()!=day:raise RuntimeError('Session parent/day changed')
            if time.monotonic()-began>11100:raise RuntimeError('Session lifetime exhausted')
            await asyncio.sleep(1)
    except BaseException as e:
        if driver.page and not driver.page.is_closed():await driver.page.screenshot(path=str(output/'failure.png'))
        write_json(output/'failure.json',dict(status='FAILED',at=time.time(),error=str(e)))
        raise
    finally:
        try:
            if lease:await lease.close()
        finally:await driver.close()

if __name__=='__main__':
    assert sys.argv[1]=='--host'
    asyncio.run(host(Path(sys.argv[2]),sys.argv[3],int(sys.argv[4])))
