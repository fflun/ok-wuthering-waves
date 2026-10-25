"""Offline browser device + native OCR/template benchmark; no game tasks are created."""
import base64
import importlib.abc
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
# Bound the complete worker (and its children) to one available vCPU.
if hasattr(os,'sched_getaffinity'):
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
class NoWindows(importlib.abc.MetaPathFinder):
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('win32','pythoncom','pywintypes','PySide6','pydirectinput','pynput')):
            raise RuntimeError('Windows/desktop dependency in Linux startup: '+name)
sys.meta_path.insert(0,NoWindows())
import cv2
import numpy as np
import psutil
from PIL import Image,ImageDraw,ImageFont
from cloud_linux_device import LinuxBrowserDeviceManager
from ok.task.TaskExecutor import TaskExecutor
from ok.feature.FeatureSet import FeatureSet
from ok.feature.Box import Box
from ok.util.GlobalConfig import GlobalConfig
from ok.util.config import Config
from ok.util.handler import ExitEvent

cv2.setNumThreads(1)
state=Path.cwd()
Config.config_folder=str(state/'config')
process=psutil.Process()
stop_sample=threading.Event()
peaks={'tree_rss_mib':0,'tree_pss_mib':0,'processes':0}

def sample():
    processes=[process]+process.children(recursive=True)
    rss=pss=0
    for item in processes:
        try:
            mem=item.memory_full_info()
            rss+=mem.rss
            pss+=getattr(mem,'pss',mem.rss)
        except psutil.Error: pass
    value={'tree_rss_mib':round(rss/2**20,2),'tree_pss_mib':round(pss/2**20,2),'processes':len(processes)}
    for key in peaks: peaks[key]=max(peaks[key],value[key])
    return value

def monitor():
    while not stop_sample.wait(.1): sample()
thread=threading.Thread(target=monitor,daemon=True)
thread.start()
report={'game_tasks_started':0,'game_urls_opened':0,'input_events_sent':0,'affinity_vcpus':len(os.sched_getaffinity(0))}
exit_event=ExitEvent()
dm=LinuxBrowserDeviceManager(exit_event)
executor=None
try:
    start=time.perf_counter()
    dm.do_start()
    fs=FeatureSet(False,str(state/'synthetic-only.json'),.002,.002,default_threshold=.95)
    executor=TaskExecutor(dm,exit_event=exit_event,feature_set=fs,global_config=GlobalConfig([]),config={'locale':'zh_CN','ocr':None})
    assert executor.thread is None and not executor.onetime_tasks and not executor.trigger_tasks
    assert executor.paused and dm.capture_method.block_input
    report['browser_device_start_seconds']=round(time.perf_counter()-start,3)
    report['browser_idle']=sample()
    assert dm.capture_method.run_in_loop(dm.capture_method.browser_page.evaluate('location.href'))=='about:blank'
    # Use one licensed font extracted into this stage, never user screenshots.
    fonts=list(state.parent.glob('fonts/usr/share/fonts/**/*.ttc'))
    assert fonts,'Missing isolated Chinese font'
    font=ImageFont.truetype(str(fonts[0]),42)
    image=Image.new('RGB',(1280,720),'white')
    draw=ImageDraw.Draw(image)
    for y,text in [(65,'领取奖励'),(145,'双倍领取'),(225,'兑换次数：2'),(305,'结晶波片 120/240')]:
        draw.text((90,y),text,font=font,fill='black')
    frame=cv2.cvtColor(np.array(image),cv2.COLOR_RGB2BGR)
    template=np.random.default_rng(731).integers(0,256,(36,56,3),dtype=np.uint8)
    frame[600:636,900:956]=template
    ok,png=cv2.imencode('.png',frame); assert ok
    # Embed synthetic pixels into a local canvas: no URL navigation or screenshot API.
    encoded=base64.b64encode(png).decode()
    capture=dm.capture_method
    async def load_fixture():
        await capture.browser_page.set_content('<style>html,body{margin:0}</style><canvas id="sr-canvas" width="1280" height="720"></canvas>')
        await capture.browser_page.evaluate('''async data => {
          const img=new Image();img.src='data:image/png;base64,'+data;await img.decode();
          document.querySelector('canvas').getContext('2d').drawImage(img,0,0);
        }''',encoded)
    capture.run_in_loop(load_fixture())
    executor.paused=False
    received=executor.next_frame()
    executor.paused=True
    assert np.array_equal(received,frame),'Device changed synthetic pixels'
    report['native_executor_frame']='1280x720, byte-identical synthetic pixels'
    # Input stays blocked at interaction and backend, even if a caller toggles its flag.
    try: dm.interaction.send_key('w')
    except RuntimeError: pass
    else: raise AssertionError('Offline interaction accepted input')
    try: capture.run_in_loop(capture.request('input',{}))
    except RuntimeError: pass
    else: raise AssertionError('Offline backend accepted input')
    report['input_block_verified']=True
    timings=[]
    for _ in range(10):
        start=time.perf_counter()
        boxes=fs.find_one_feature(received,'synthetic',template=template,threshold=.99,limit=1)
        timings.append((time.perf_counter()-start)*1000)
        assert len(boxes)==1 and abs(boxes[0].x-900)<=1 and abs(boxes[0].y-600)<=1
    blank=np.full_like(frame,255)
    assert not fs.find_one_feature(blank,'synthetic',template=template,threshold=.99,limit=1)
    report['template']={'engine':'native FeatureSet.find_one_feature','positive_runs':10,'negative_runs':1,
        'mean_ms':round(statistics.mean(timings),2),'max_ms':round(max(timings),2),'memory':sample()}
    roi_times=[]
    for _ in range(10):
        start=time.perf_counter()
        boxes=fs.find_one_feature(received,'synthetic',template=template,box=Box(880,580,100,80),threshold=.99,limit=1)
        roi_times.append((time.perf_counter()-start)*1000)
        assert len(boxes)==1 and abs(boxes[0].x-900)<=1 and abs(boxes[0].y-600)<=1
    report['template']['roi_mean_ms']=round(statistics.mean(roi_times),2)
    report['template']['roi_max_ms']=round(max(roi_times),2)
    executor.config['ocr']={'default':{'lib':'onnxocr','params':{'use_openvino':False,'use_npu':False}}}
    # Installed models are bundled; reject network access by the Python OCR process.
    def audit(event,args):
        if event=='socket.connect': raise RuntimeError('Offline OCR attempted network access')
    sys.addaudithook(audit)
    start=time.perf_counter()
    ocr=executor.ocr_lib()
    report['ocr_providers']={'detector':ocr.text_detector.session.get_providers(),
                             'recognizer':ocr.text_recognizer.session.get_providers()}
    report['ocr_load_seconds']=round(time.perf_counter()-start,3)
    report['ocr_loaded_memory']=sample()
    results=[]
    for label,pixels in [('full_clean',frame),('text_roi',frame[40:390,60:750]),('blank',blank)]:
        times=[]; texts=[]
        for _ in range(3 if label!='blank' else 1):
            start=time.perf_counter()
            result=ocr.ocr(pixels)
            times.append((time.perf_counter()-start)*1000)
            texts=[item[1][0] for item in result[0]] if result and result[0] else []
        joined=''.join(texts).replace(' ','')
        if label=='blank': assert not texts,texts
        else:
            for required in ['领取奖励','双倍领取','兑换次数','120/240']:
                assert required in joined,(label,required,texts)
        results.append({'fixture':label,'recognized':texts,'runs':len(times),'mean_ms':round(statistics.mean(times),2),'max_ms':round(max(times),2)})
    report['ocr_results']=results
    report['final_memory']=sample()
    report['blocked_page_requests']=len(capture.blocked_requests)
    assert capture.browser_page.url=='about:blank'
    assert executor.thread is None and not executor.onetime_tasks and not executor.trigger_tasks
    report['status']='PASS_OFFLINE_DEVICE_OCR_TEMPLATE'
finally:
    if executor: executor.destroy()
    dm.close()
    exit_event.set()
    stop_sample.set();thread.join(timeout=2)
    report['peak_memory']=peaks
    children=process.children(recursive=True)
    report['remaining_child_processes']=len(children)
    assert not children,'Browser child processes did not exit'
    Path('runtime-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
