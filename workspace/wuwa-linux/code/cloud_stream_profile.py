"""Server-only cloud-client profile. No game input, spending, or client restart."""
import asyncio,json,time
from pathlib import Path

async def close_quality_menu(page, menu, panel):
 # The left-side provider menu can be visible without an overlay mask.
 # Its documented Alt+Q toggle is safe only after positive menu observations.
 states=[]
 async def panel_visible():
  count=await panel.count()
  if count==0:return False  # Provider removes both rows after closing.
  if count not in (1,2):raise RuntimeError('Cloud quality rows ambiguous')
  visible=[await panel.nth(i).is_visible() for i in range(count)]
  if any(visible)!=all(visible):raise RuntimeError('Cloud quality rows disagree')
  return all(visible)
 for _ in range(2):
  states.append((await menu.is_visible(),await panel_visible()))
  await asyncio.sleep(.2)
 if states==[(False,False),(False,False)]:
  return {'method':'already_closed','hidden_frames':2}
 if states!=[(True,True),(True,True)]:
  raise RuntimeError('Cloud quality menu changed before closing')
 mask=page.locator('.cloud-helper-mask')
 count=await mask.count()
 if count>1:raise RuntimeError('Cloud helper close mask ambiguous')
 if count==1 and await mask.is_visible():
  await mask.click(position={'x':1200,'y':680},timeout=3000)
  method='mask'
 else:
  await page.keyboard.press('Alt+q')
  method='verified_menu_shortcut'
 try:
  await menu.wait_for(state='hidden',timeout=3000)
 except Exception:
  if method!='mask' or not await menu.is_visible():raise
  await page.keyboard.press('Alt+q')
  method='mask_then_shortcut'
  await menu.wait_for(state='hidden',timeout=5000)
 for _ in range(2):
  if await menu.is_visible() or await panel_visible():
   raise RuntimeError('Cloud quality menu closure not verified')
  await asyncio.sleep(.2)
 return {'method':method,'hidden_frames':2}

def require_profile(samples, *, allow_1080=False):
 # Windows CloudCapture already resizes either supported 16:9 source to 720p.
 # Verify that same mapping here; source size remains truthful in the receipt.
 from cloud_bridge import game_rect
 if len(samples)!=2:raise RuntimeError('Two fresh profile observations required')
 for x in samples:
  m=x.get('metrics',{})
  if (x.get('fps')!=60 or m.get('source') not in ([1280,720],[1920,1080])
      or m.get('viewport')!=[1280,720] or not m.get('ready')):
   raise RuntimeError('Unsupported capture source, viewport, or 60 FPS profile')
  rect=game_rect(m)
  if any(abs(rect[k]-v)>.5 for k,v in dict(x=0,y=0,width=1280,height=720).items()):
   raise RuntimeError('Game surface does not fill the original 720p capture viewport')
 first,last=[x['metrics'] for x in samples]
 if (first['source']!=last['source'] or first.get('kind')!=last.get('kind')
     or last.get('stream',{}).get('time',0)<=first.get('stream',{}).get('time',0)):
  raise RuntimeError('Source changed or profile video is stale')

async def configure_stream(driver, *, allow_1080=False):
 page=driver.page
 # A fresh decoder surface can exist behind the provider loading overlay.
 loading=page.get_by_text('游戏启动中，请耐心等待~',exact=True)
 if await loading.count():await loading.wait_for(state='hidden',timeout=120000)
 ball=page.locator('.helper-ball')
 await ball.wait_for(state='visible',timeout=20000)
 menu=page.locator('.menu-item').filter(has_text='画质调整')
 if await menu.count()!=1:raise RuntimeError('Cloud quality menu is ambiguous')
 for _ in range(2):
  if await menu.is_visible():break
  await page.keyboard.press('Alt+q')
  await asyncio.sleep(.2)
 if not await menu.is_visible():raise RuntimeError('Cloud quality menu stayed closed')
 await menu.locator('.dropdown-target').dispatch_event('mouseenter')
 panel=page.locator('.quality-list')
 await page.get_by_text('帧率选择',exact=True).wait_for(state='visible',timeout=3000)
 labels=await panel.locator('.quality-item').all_text_contents()
 if set(labels)!={'超清','均衡','30帧','60帧'} or len(labels)!=4:
  raise RuntimeError('Unsupported cloud quality options; no settings changed')
 before=await panel.locator('.active').all_text_contents()
 for text in ('超清','60帧'):
  target=panel.locator('.quality-item').filter(has_text=text)
  if await target.count()!=1:raise RuntimeError('Ambiguous cloud quality option')
  if 'active' not in (await target.get_attribute('class') or '').split():
   await target.click(timeout=3000)
   await asyncio.sleep(.3)
  if 'active' not in (await target.get_attribute('class') or '').split():
   raise RuntimeError('Cloud quality change not confirmed')
 after=await panel.locator('.active').all_text_contents()
 if set(after)!={'超清','60帧'}:raise RuntimeError('Cloud quality profile not confirmed')
 closure=await close_quality_menu(page,menu,panel)
 # Preserve the user-approved ultra/60 profile; no SDK quality/resolution setter.
 sdk={'provider':await page.evaluate("()=>window.tencentGamePlayer?'tencent':(window.WLCG?'welink':'unknown')"),
      'quality':'超清','fps':60,'resolution_requested':None}
 samples=[]
 for _ in range(2):
  await asyncio.sleep(2)
  m=await driver.metrics()
  playback=await page.evaluate("""()=>[...document.querySelectorAll('video')].filter(v=>v.videoWidth).map(v=>({
    source:[v.videoWidth,v.videoHeight],time:v.currentTime,total:v.getVideoPlaybackQuality().totalVideoFrames,
    dropped:v.getVideoPlaybackQuality().droppedVideoFrames}))""")
  samples.append({'metrics':m,'fps':60,'configured_fps':60,'quality':'超清','playback':playback})
 record={'at':time.time(),'before':before,'after':after,'closure':closure,'sdk':sdk,'samples':samples[-2:],
         'native_720p':all(x['metrics'].get('source')==[1280,720] for x in samples[-2:])}
 print('CLOUD_SERVER_STREAM_PROFILE '+json.dumps(record,ensure_ascii=False),flush=True)
 record['explicit_one_off_1080_allowance']=allow_1080
 require_profile(record['samples'],allow_1080=allow_1080)
 record['capture_compatible']=True
 record['recognizer_resolution']=[1280,720]
 return record
