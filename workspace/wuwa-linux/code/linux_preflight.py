"""No-login acceptance of current task construction and Linux ownership."""
import os,sys,tempfile,time,subprocess,json
from pathlib import Path
from cloud_autorun_state import ProcessLock
from cloud_process import spawn_options,terminate_tree
import psutil
root=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp)/'lock'
 with ProcessLock(p):
  child=subprocess.run([sys.executable,'-c',"from cloud_autorun_state import ProcessLock;\nwith ProcessLock(__import__('sys').argv[1]): pass",str(p)],capture_output=True)
  assert child.returncode!=0
 with ProcessLock(p):pass
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],**spawn_options())
 terminate_tree(child); assert child.poll() is not None
 from config import config
 from linux_app import LinuxOK
 cfg=dict(config,config_folder=str(Path(tmp)/'configs'),locale='zh_CN')
 cfg['template_matching']=dict(cfg['template_matching'],coco_feature_json=str(root.parent/'assets/coco_annotations.json'))
 cfg['echo_model_path']=str(root.parent/'assets/echo_model/echo.onnx')
 app=LinuxOK(cfg)
 assert app.task_executor.thread is None
 assert app.device_manager.capture_method is None
 assert not any(t.enabled for t in app.task_executor.onetime_tasks)
 names=[type(t).__name__ for t in app.task_executor.onetime_tasks]
 assert {'DailyTask','GardenTask','FarmEchoTask','NightmareNestTask','ForgeryTask','SimulationTask','TacetTask'}<=set(names)
 assert app.task_executor.ocr_lib is not None
 app.exit_event.set()
 if app.task_executor._ocr_init_thread:app.task_executor._ocr_init_thread.join(timeout=20)
 assert not psutil.Process().children(recursive=True)
 print(json.dumps({'status':'PASS_CURRENT_TASK_CONSTRUCTION','tasks':names,'lock':'exclusive','process_cleanup':'pass','game_started':False}))
