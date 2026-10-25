"""Server entry: no task runs unless explicit original task arguments are supplied."""
import argparse,os,runpy
from pathlib import Path
root=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser()
 p.add_argument('mode',choices=['preflight','dynamic','memory','regression','run'],default='preflight',nargs='?')
 p.add_argument('task_args',nargs=argparse.REMAINDER)
 args=p.parse_args()
 os.chdir(root)
 if args.mode!='run':
  if args.task_args:p.error('Probe modes do not take game arguments')
  file={'preflight':'linux_preflight.py','dynamic':'linux_dynamic_probe.py','memory':'linux_memory_probe.py','regression':'linux_regression.py'}[args.mode]
  runpy.run_path(str(root/file),run_name='__main__');return
 task_args=args.task_args
 if task_args and task_args[0]=='--':task_args=task_args[1:]
 if '--connect' not in task_args or '--background' not in task_args:
  p.error('Live mode requires explicit --connect --background; never falls back to desktop')
 from cloud_autorun_state import ProcessLock
 state=root.parent/'okww-cloud-session/background'
 # Retain ordinary ledger/acceptance checks in the original automatic entry.
 # This manual path is only for bounded acceptance after a separate server login.
 if not (state/'game-profile/Default').is_dir():
  raise RuntimeError('SERVER_LOGIN_REQUIRED: no server browser account profile; Windows session was not copied')
 with ProcessLock(state/'runner.lock'):
  from main_cloud_daily import main as native_main
  native_main(task_args)

if __name__=='__main__':main()

