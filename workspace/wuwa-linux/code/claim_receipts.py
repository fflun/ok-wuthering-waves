"""Permanent evidence after verified natural-waveplate claims; no input methods."""
import os,time,json
from pathlib import Path
def before(task):
 if not getattr(task,'_cloud_daily_no_refill',False):return None
 folder=os.environ.get('OKWW_DAILY_OUTPUT')
 if not folder:return None
 import cv2
 output=Path(folder);output.mkdir(parents=True,exist_ok=True)
 stem=str(time.time_ns());path=output/(stem+'-claim-before.png')
 if not cv2.imwrite(str(path),task.frame):raise RuntimeError('Pre-claim evidence could not be saved')
 return output,stem,str(path)
def after(task,context,current,reserve,cost):
 if context is None:return
 import cv2
 output,stem,before_image=context;path=output/(stem+'-claim-after.png')
 if not cv2.imwrite(str(path),task.frame):raise RuntimeError('Verified claim evidence could not be saved; reconcile pending journal')
 result=dict(at=time.time(),run_id=os.environ.get('OKWW_RUN_ID'),before=current,reserve_before=reserve,cost=cost,
  remaining=getattr(task,'_cloud_last_claim_remaining',None),deduction_verified=True,before_image=before_image,after_image=str(path))
 with (output/'verified-claims.jsonl').open('a') as f:
  f.write(json.dumps(result)+'\n');f.flush();os.fsync(f.fileno())
 task.log_info('CLOUD_NATURAL_CLAIM_VERIFIED '+json.dumps(result))
 return result
