"""Current browser: dynamic local video, CDP input and memory; no login or URL."""
import asyncio,json,psutil,time
from pathlib import Path
from cloud_background_browser import BackgroundBrowser
from cloud_background_startup import wait_fresh_surface
FIXTURE='''<video autoplay muted playsinline style="width:1280px;height:720px"></video><script>
const c=document.createElement('canvas');c.width=1280;c.height=720;const ctx=c.getContext('2d');let n=0;
window.keys=[];addEventListener('keydown',e=>keys.push(e.code));
setInterval(()=>{ctx.fillStyle='#123';ctx.fillRect(0,0,1280,720);ctx.fillStyle='white';ctx.fillRect((n++*10)%1200,100,80,80)},70);
document.querySelector('video').srcObject=c.captureStream(15);
</script>'''
async def main():
 import tempfile
 report={'game_urls_opened':0,'game_tasks_started':0};proc=psutil.Process();peak=0
 with tempfile.TemporaryDirectory() as tmp:
  b=BackgroundBrowser(Path(tmp)/'profile',synthetic=True)
  try:
   await b.start();await b.page.set_content(FIXTURE)
   await wait_fresh_surface(b,timeout=15)
   frames=[]
   for i in range(12):
    start=time.monotonic();f=await b.frame();frames.append((time.monotonic()-start)*1000)
    pss=0
    for p in [proc,*proc.children(recursive=True)]:
     try:pss+=p.memory_full_info().pss
     except psutil.Error:pass
    peak=max(peak,pss)
   try:await b.key('KeyW','w',87,True)
   except RuntimeError:pass
   else:raise AssertionError('input gate failed')
   b.input_enabled=True;await b.key('KeyW','w',87,True);await b.release()
   assert await b.page.evaluate('window.keys')==['KeyW']
   report.update(status='PASS_DYNAMIC_BROWSER_INPUT',frames=len(frames),mean_capture_ms=round(sum(frames)/len(frames),1),peak_pss_mib=round(peak/2**20,1))
  finally:await b.close()
 await asyncio.sleep(.3)
 assert not proc.children(recursive=True)
 report['remaining_children']=0;print(json.dumps(report))
asyncio.run(main())
