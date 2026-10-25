"""Offline Linux imports and synthetic frame benchmark. No OK instance or task execution."""
import importlib
import importlib.abc
import json
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BLOCKED = ('win32','pythoncom','pywintypes','pydirectinput','pynput','PySide6','playwright')
class NoDesktopImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(BLOCKED):
            raise RuntimeError('Forbidden desktop/browser import during offline probe: '+fullname)
sys.meta_path.insert(0,NoDesktopImports())
def audit(event, args):
    if event in {'socket.connect','socket.bind','subprocess.Popen','os.system','os.exec','os.posix_spawn','os.fork'}:
        raise RuntimeError('Offline probe prohibited side effect: '+event)
sys.addaudithook(audit)
start = time.perf_counter()
cpu = time.process_time()
modules = [
    'src.platform_io','src.task.MouseResetTask','src.task.BaseCombatTask',
    'src.task.DailyTask','src.task.TacetTask','src.task.ForgeryTask',
    'src.char.Aemeath','src.char.Hiyuki','cloud_daily_runtime','cloud_adapter','config',
    'ok.task.TaskExecutor',
]
loaded = []
for name in modules:
    importlib.import_module(name)
    loaded.append(name)
from config import config
for name, _ in config.get('onetime_tasks', []) + config.get('trigger_tasks', []):
    if name not in loaded:
        importlib.import_module(name)
        loaded.append(name)
import psutil
import numpy as np
import cv2
cv2.setNumThreads(1)
from cloud_adapter import install
install(Path.cwd()/'never-created-pending.json')
assert not (Path.cwd()/'never-created-pending.json').exists()
import_seconds = time.perf_counter()-start
import_cpu = time.process_time()-cpu
process = psutil.Process()
import_rss = process.memory_info().rss
assert not process.children(), 'No child processes allowed'
assert not process.net_connections(), 'No sockets allowed'
assert not any(name.startswith(BLOCKED) for name in sys.modules)
# Synthetic non-game pixels only; no screenshot or account data is read.
frame = np.zeros((720,1280,3),dtype=np.uint8)
frame[100:500,200:800] = (50,100,200)
bench_start = time.perf_counter()
bench_cpu = time.process_time()
for _ in range(100):
    ok,data = cv2.imencode('.png',frame)
    assert ok
    restored = cv2.imdecode(data,cv2.IMREAD_COLOR)
    assert restored.shape == frame.shape
bench_seconds = time.perf_counter()-bench_start
import threading
assert [t for t in threading.enumerate() if t is not threading.main_thread()] == []
result = dict(status='PASS_IMPORT_AND_SYNTHETIC_ONLY',python=sys.version.split()[0],
    modules=loaded,import_seconds=round(import_seconds,3),import_cpu_seconds=round(import_cpu,3),
    import_rss_mib=round(import_rss/2**20,2),peak_rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),
    png_roundtrips=100,png_roundtrip_mean_ms=round(bench_seconds*10,3),
    png_cpu_seconds=round(time.process_time()-bench_cpu,3),
    browsers_started=0,game_tasks_started=0,network_connections=0,
    limitation='No OCR model, real stream, task execution, OK/DeviceManager construction, or unattended validation')
Path('import-resource-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
