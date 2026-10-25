"""Bounded recognition of existing Linux capture files; no browser/input/task owner."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time

os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
import cv2
import numpy as np
import psutil
from onnxocr.onnx_paddleocr import ONNXPaddleOcr
from ok.feature.FeatureSet import FeatureSet

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
parser.add_argument('--assets', required=True)
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
cv2.setNumThreads(1)
process = psutil.Process()
peak = {'rss_mib': 0, 'pss_mib': 0}
done = threading.Event()
def sample_memory():
    while not done.wait(.1):
        mem = process.memory_full_info()
        peak['rss_mib'] = max(peak['rss_mib'], round(mem.rss / 2**20, 2))
        peak['pss_mib'] = max(peak['pss_mib'], round(mem.pss / 2**20, 2))
monitor = threading.Thread(target=sample_memory, daemon=True)
monitor.start()
reader = '''import base64,json,time
from pathlib import Path
p=Path('/home/pinwheel-desktop/.local/share/pinwheel-wuwa')
s=json.loads((p/'status.json').read_text())
r={'status':s,'status_age_s':time.time()-(p/'status.json').stat().st_mtime}
f=p/'last-frame.png'
if s.get('state')=='VIDEO_CAPTURE_CANDIDATE' and f.exists():
 r.update(frame_age_s=time.time()-f.stat().st_mtime,frame_mtime=f.stat().st_mtime,png=base64.b64encode(f.read_bytes()).decode())
print(json.dumps(r))
'''
report = {'scope': 'existing video capture files only', 'input_events_sent': 0,
          'game_tasks_started': 0, 'samples': [], 'ocr': [], 'templates': []}
try:
    ocr = None
    fs = FeatureSet(False, str(Path(args.assets)/'coco_annotations.json'), .002, .002, default_threshold=.8)
    for index in range(8):
        record = json.loads(subprocess.check_output(['sudo','-n','-u','pinwheel-desktop','python3','-c',reader]))
        raw = record.pop('png', None)
        report['samples'].append(record)
        assert not record['status']['automation_enabled'] and not record['status']['input_enabled']
        if raw and record['status_age_s'] < 15 and record['frame_age_s'] < 15:
            png = base64.b64decode(raw)
            frame = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                record['decode_error'] = True
                continue
            record['sha256'] = hashlib.sha256(png).hexdigest()
            record['size'] = [frame.shape[1], frame.shape[0]]
            (out/'latest-frame.png').write_bytes(png)
            if ocr is None:
                start = time.perf_counter()
                ocr = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=False)
                report['ocr_load_s'] = round(time.perf_counter()-start, 3)
                report['providers'] = ocr.text_recognizer.session.get_providers()
            if index in (0,3,7) or not report['ocr']:
                start = time.perf_counter()
                result = ocr.ocr(frame)
                # Keep HUD text and coordinates; do not publish account-number text.
                texts = [{'text':item[1][0], 'confidence':float(item[1][1]),
                          'quad':np.asarray(item[0]).tolist()}
                         for item in (result[0] if result and result[0] else [])
                         if not any(ch.isdigit() for ch in item[1][0]) or len(''.join(filter(str.isdigit,item[1][0])))<8]
                report['ocr'].append({'sample':index,'ms':round((time.perf_counter()-start)*1000,2),'items':texts})
                matches = []
                start = time.perf_counter()
                for name in ['char_1_text','char_2_text','char_3_text','char_hiyuki','char_linnai','char_moning','char_moning_new']:
                    boxes = fs.find_one_feature(frame, name, threshold=.8, limit=1)
                    matches.append({'name':name,'matches':[{'x':b.x,'y':b.y,'confidence':float(b.confidence)} for b in boxes]})
                report['templates'].append({'sample':index,'ms':round((time.perf_counter()-start)*1000,2),'items':matches})
        if index < 7:
            time.sleep(5)
    hashes = {x['sha256'] for x in report['samples'] if 'sha256' in x}
    report['unique_frame_hashes'] = len(hashes)
    report['result'] = 'LIVE_FRAMES_RECOGNIZED' if len(hashes)>1 and report['ocr'] else 'NOT_VERIFIED'
finally:
    done.set()
    monitor.join(timeout=2)
    report['worker_peak_memory'] = peak
    (out/'recognition.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('samples','ocr','templates')},ensure_ascii=False))
