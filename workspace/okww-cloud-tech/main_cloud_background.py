"""Bounded Windows hidden-browser probes; no daily tasks or startup registration."""
import argparse
import asyncio
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import statistics
import threading
import time

from cloud_background_browser import BackgroundBrowser

ROOT = Path(__file__).resolve().parent
STATE = ROOT.parent/'okww-cloud-session'/'background'
FIXTURE = '''<!doctype html><title>OKWW background video probe</title>
<style>html,body{margin:0}video{width:1280px;height:720px;object-fit:contain}</style>
<video autoplay muted playsinline></video><script>
const source=document.createElement('canvas');source.width=1280;source.height=720;
const ctx=source.getContext('2d');let tick=0;window.keys=[];window.moves=0;
addEventListener('keydown',e=>window.keys.push(e.code));
addEventListener('mousemove',()=>window.moves++);
setInterval(()=>{ctx.fillStyle='#123';ctx.fillRect(0,0,1280,720);
 ctx.fillStyle='#0f8';ctx.fillRect((tick++*13)%1150,250,130,130);
 ctx.fillStyle='#fff';ctx.font='40px sans-serif';ctx.fillText('FRAME '+tick,50,70);},33);
document.querySelector('video').srcObject=source.captureStream(30);
</script>'''


class HostMonitor:
    """Read-only focus observation; no titles, text or keys from the user's apps."""
    def __init__(self):
        self.stop = threading.Event()
        self.rows = []
        self.thread = threading.Thread(target=self.run, daemon=True)
    def run(self):
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        while not self.stop.is_set():
            hwnd=user32.GetForegroundWindow()
            pid=wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            self.rows.append((time.monotonic(),pid.value))
            self.stop.wait(.02)
    def finish(self, owned):
        self.stop.set();self.thread.join(timeout=2)
        return {'samples':len(self.rows),'owned_browser_foreground_samples':sum(pid in owned for _,pid in self.rows),
                'foreground_app_changes':sum(a[1]!=b[1] for a,b in zip(self.rows,self.rows[1:]))}


async def run(args):
    import psutil
    STATE.mkdir(parents=True,exist_ok=True)
    synthetic=args.mode=='synthetic'
    profile=STATE/('synthetic-profile' if synthetic else 'game-profile')
    browser=BackgroundBrowser(profile,headless=args.mode!='login',synthetic=synthetic)
    monitor=HostMonitor()
    monitor.thread.start()
    proc=psutil.Process()
    owned=set()
    report={'mode':args.mode,'game_tasks_started':0,'frames':[],'errors':[],
            'peak_tree_rss_mib':0,'input_events_sent':0}
    try:
        await browser.start()
        owned.update(p.pid for p in proc.children(recursive=True))
        if args.mode=='login':
            print('LOGIN_READY: manually log in and enter a safe game scene. Type done here when ready.',flush=True)
            while True:
                command=await asyncio.to_thread(input)
                if command.strip()=='status':
                    print('METRICS '+json.dumps(await browser.metrics(),ensure_ascii=False),flush=True)
                elif command.strip()=='snapshot':
                    await browser.page.screenshot(path=str(STATE/'login-page.png'))
                    print('LOGIN_SNAPSHOT_SAVED',flush=True)
                elif command.strip()=='enter':
                    await browser.page.get_by_role('button',name='进入游戏',exact=True).click(timeout=5000)
                    print('ENTER_CLICKED',flush=True)
                elif command.strip()=='done':
                    break
            report['status']='LOGIN_SESSION_SAVED'
            return
        if synthetic:
            await browser.page.set_content(FIXTURE)
            await browser.page.wait_for_function('document.querySelector("video").readyState>=2')
        else:
            print('GAME_PAGE_OPENED_INPUT_DISABLED',flush=True)
            if args.enter_game:
                button=browser.page.get_by_role('button',name='进入游戏',exact=True)
                try:
                    await button.click(timeout=15000)
                    print('GAME_ENTER_CLICKED',flush=True)
                except Exception:
                    # Never guess other buttons (renewal, payment or login) by coordinates.
                    await browser.page.screenshot(path=str(STATE/'game-page.png'))
                    print('GAME_ENTER_UNAVAILABLE: saved page screenshot',flush=True)
            video_deadline=time.monotonic()+120
            while time.monotonic()<video_deadline:
                if (await browser.metrics()).get('ready'):
                    break
                await asyncio.sleep(2)
            if not (await browser.metrics()).get('ready'):
                await browser.page.screenshot(path=str(STATE/'game-page.png'))
                report['status']='NO_GAME_VIDEO'
                return
        end=time.monotonic()+args.seconds
        last_media=None
        while time.monotonic()<end:
            started=time.monotonic()
            try:
                frame=await browser.frame()
                data=base64.b64decode(frame.pop('data'),validate=True)
                if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise RuntimeError('Invalid PNG')
                import cv2
                import numpy as np
                pixels=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
                mean=float(pixels.mean()) if pixels is not None else 0
                fresh=frame.get('freshness') or {}
                media=fresh.get('mediaTime')
                if media is not None and last_media is not None and media<=last_media:
                    raise RuntimeError('Video time failed to advance')
                last_media=media
                report['frames'].append({'ms':round((time.monotonic()-started)*1000,2),
                    'media_time':media,'presented_frames':fresh.get('presentedFrames'),
                    'source':frame['metrics']['source'],'visibility':frame['metrics']['visibility'],
                    'kind':frame['metrics']['kind'],'mean':mean,
                    'sha256':hashlib.sha256(data).hexdigest()})
                (STATE/'last-frame.png').write_bytes(data)
                if synthetic:
                    browser.input_enabled=True
                    await browser.key('KeyW','w',87,True)
                    await browser.key('KeyW','w',87,False)
                    await browser.cdp.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':400+len(report['frames'])%20,'y':400})
                    browser.input_enabled=False
                    report['input_events_sent']+=3
            except Exception as exc:
                report['errors'].append({'type':type(exc).__name__,'message':str(exc)[:180]})
                if len(report['errors'])>=3:
                    break
            children=proc.children(recursive=True)
            owned.update(p.pid for p in children)
            rss=proc.memory_info().rss
            for child in children:
                try:rss+=child.memory_info().rss
                except psutil.Error:pass
            report['peak_tree_rss_mib']=max(report['peak_tree_rss_mib'],round(rss/2**20,2))
            await asyncio.sleep(.5)
        if synthetic:
            report['page_input_received']=await browser.page.evaluate('({keys:window.keys.length,moves:window.moves})')
        valid=[f for f in report['frames'] if f['mean']>2]
        report['status']='PASS_CAPTURE' if (len(valid)>=20 and len({f['sha256'] for f in valid})>=3
            and all(f['mean']>2 for f in report['frames'][-20:]) and not report['errors']) else 'NOT_VERIFIED'
        if args.keep_open and not synthetic:
            print('PROBE_HOLD: status / snapshot / keytest / menu / escape / quit',flush=True)
            while True:
                command=(await asyncio.to_thread(input)).strip()
                if command=='quit':
                    break
                if command=='status':
                    print('METRICS '+json.dumps(await browser.metrics(),ensure_ascii=False),flush=True)
                elif command=='snapshot':
                    frame=await browser.frame()
                    (STATE/'game-current.png').write_bytes(base64.b64decode(frame['data']))
                    print('GAME_SNAPSHOT_SAVED',flush=True)
                elif command in ('keytest','menu','escape'):
                    code,key,vk={'keytest':('KeyW','w',87),'menu':('F2','F2',113),'escape':('Escape','Escape',27)}[command]
                    browser.input_enabled=True
                    try:
                        await browser.key(code,key,vk,True)
                        await asyncio.sleep(.12)
                    finally:
                        await browser.key(code,key,vk,False)
                        browser.input_enabled=False
                    report['input_events_sent']+=2
                    print('GAME_INPUT_SENT '+command,flush=True)
    finally:
        await browser.close()
        report['focus']=monitor.finish(owned)
        if args.mode!='login' and report['focus']['owned_browser_foreground_samples']:
            report['status']='FAILED_FOREGROUND_INTERFERENCE'
        report['remaining_owned_processes']=[p.pid for p in proc.children(recursive=True)]
        report['frame_count']=len(report['frames'])
        if report['frames']:
            report['mean_capture_ms']=round(statistics.mean(x['ms'] for x in report['frames']),2)
            report['unique_frame_hashes']=len({x['sha256'] for x in report['frames']})
        (STATE/(args.mode+'-result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in ('frames',)},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['synthetic','login','game'])
    parser.add_argument('--seconds',type=int,default=120)
    parser.add_argument('--enter-game',action='store_true',help='Click only the official Enter game button')
    parser.add_argument('--keep-open',action='store_true',help='Keep this owned session for explicit verification commands')
    options=parser.parse_args()
    if not 10<=options.seconds<=600:parser.error('seconds must be 10..600')
    asyncio.run(run(options))
