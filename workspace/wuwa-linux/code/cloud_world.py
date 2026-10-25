"""Positive quest-world globe variant; two fresh frames, never a HUD-only guess."""
from pathlib import Path
import cv2
def verified_world(task):
 if task.in_world():return True
 frame=getattr(task,'frame',None)
 if frame is None:return False
 ok,index,count=task.in_team()
 if not ok or count!=3 or index not in (0,1,2):return False
 template=cv2.imread(str(Path(__file__).with_name('cloud_world_globe_quest.png')),cv2.IMREAD_GRAYSCALE)
 if template is None:raise RuntimeError('Quest-world positive globe template missing')
 gray=cv2.cvtColor(frame[12:60,0:50],cv2.COLOR_BGR2GRAY)
 score=float(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED).max())
 previous=getattr(task,'_cloud_world_positive',None)
 if score<.90:
  task._cloud_world_positive=None
  return False
 task._cloud_world_positive=frame
 confirmed=previous is not None and previous is not frame
 if confirmed:task.log_info(f'CLOUD_WORLD quest globe verified on two fresh frames score={score:.3f}')
 return confirmed
