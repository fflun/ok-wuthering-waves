"""Linux-only application shell; original tasks and executor remain unchanged."""
from types import SimpleNamespace
from ok import og
from ok.util.handler import ExitEvent
from ok.util.config import Config
from ok.util.GlobalConfig import GlobalConfig,register_basic_options
from ok.feature.FeatureSet import FeatureSet
from ok.task.TaskExecutor import TaskExecutor
from ok.core.task_manager import TaskManager
from cloud_linux_device import LinuxBrowserDeviceManager
from cloud_background_runtime import BackgroundCapture
from cloud_daily_runtime import CloudInteraction

class GameDevice(LinuxBrowserDeviceManager):
    def do_start(self,notify=True):
        if self.capture_method is None:
            self.capture_method=BackgroundCapture(self.browser_config,self.exit_event)
            self.interaction=CloudInteraction(self.capture_method)
        try:
            self.capture_method.start_browser(); self.update_browser_device()
        except BaseException:
            self.close(); raise

class Controller:
    def __init__(self,owner): self.owner=owner
    def start_device(self):
        dm=self.owner.device_manager
        return bool(dm.capture_method and dm.capture_method.connected())
    def do_start(self,task,exit_after=False):
        ex=self.owner.task_executor
        if self.owner.exit_event.is_set() or not self.start_device():
            raise RuntimeError('Linux browser is not ready')
        if ex.current_task or any(t.enabled for t in ex.onetime_tasks):
            raise RuntimeError('Another task is active')
        task.exit_after_task=exit_after
        task._enabled=True; task.info_clear(); ex.enqueue_onetime_task(task)
        ex.start()
        return True

class LinuxOK:
    def __init__(self,config):
        self.config=dict(config); self.exit_event=ExitEvent()
        self.config['locale']='zh_CN'
        self.config['ocr']={'lib':'onnxocr','auto_simplify':True,
                            'params':{'use_openvino':False,'use_npu':False,'num_threads':1}}
        Config.config_folder=self.config['config_folder']
        self.global_config=GlobalConfig(self.config.get('global_configs'))
        register_basic_options(self.global_config)
        og.config=self.config; og.global_config=self.global_config; og.ok=self; og.use_dml=False
        self.device_manager=GameDevice(self.exit_event,self.config.get('browser'))
        from ok.util.collection import parse_ratio
        self.device_manager.supported_ratio=parse_ratio(self.config.get('supported_resolution',{}).get('ratio'))
        og.device_manager=self.device_manager
        matching=self.config['template_matching']
        self.feature_set=FeatureSet(False,matching['coco_feature_json'],
            default_horizontal_variance=matching.get('default_horizontal_variance',.002),
            default_vertical_variance=matching.get('default_vertical_variance',.002),
            default_threshold=matching.get('default_threshold',.7),
            feature_processor=matching.get('feature_processor'),
            hcenter_features=matching.get('hcenter_features'),vcenter_features=matching.get('vcenter_features'))
        self.task_executor=TaskExecutor(self.device_manager,exit_event=self.exit_event,
            wait_until_settle_time=self.config.get('wait_until_settle_time',0),feature_set=self.feature_set,
            config_folder=Config.config_folder,debug=False,global_config=self.global_config,config=self.config)
        og.executor=self.task_executor
        self.headless_app=SimpleNamespace(debug=False,locale='zh_CN',tr=lambda s:s,
            get_overlay_view=lambda:None,start_controller=Controller(self),exit_event=self.exit_event)
        og.app=self.headless_app
        from src.globals import Globals
        og.my_app=Globals(self.exit_event)
        self.task_manager=TaskManager(self.task_executor,self.headless_app,
            onetime_tasks=self.config.get('onetime_tasks',[]),trigger_tasks=self.config.get('trigger_tasks',[]),
            scene=self.config.get('scene'))
        og.task_manager=self.task_manager
    def get_onetime_task(self,kind):
        return next(t for t in self.task_executor.onetime_tasks if isinstance(t,kind))
