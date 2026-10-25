"""Positive active timer marker; can never approve victory or spending."""
from pathlib import Path
from functools import lru_cache
import cv2
@lru_cache(maxsize=1)
def template():
 image=cv2.imread(str(Path(__file__).with_name('cloud_material_clock.png')),cv2.IMREAD_GRAYSCALE)
 if image is None:raise RuntimeError('Positive combat timer template missing')
 return image
def active_timer(frame):
 if frame is None or frame.shape[:2]!=(720,1280):return False
 gray=cv2.cvtColor(frame[83:120,570:617],cv2.COLOR_BGR2GRAY)
 return float(cv2.matchTemplate(gray,template(),cv2.TM_CCOEFF_NORMED).max())>=.90
