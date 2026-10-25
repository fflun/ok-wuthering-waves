"""Compensate cloud video color drift before the native ring-shape detector."""
import cv2
import numpy as np


def normalize_ring_color(image, color_range):
    # Hue tolerates the cloud video's muted brightness/saturation. Geometry,
    # annulus, component size and full-ring decision remain native.
    center=np.uint8([[[sum(color_range[k])//2 for k in ('b','g','r')]]])
    hue=int(cv2.cvtColor(center,cv2.COLOR_BGR2HSV)[0,0,0])
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    distance=np.abs(hsv[:,:,0].astype(np.int16)-hue)
    distance=np.minimum(distance,180-distance)
    mask=(distance<=10)&(hsv[:,:,1]>=60)&(hsv[:,:,2]>=100)
    result=np.zeros_like(image)
    result[mask]=center[0,0]
    return result


def install():
    from src.task.BaseCombatTask import BaseCombatTask
    if getattr(BaseCombatTask,'_cloud_concerto_color',False):return
    original=BaseCombatTask.count_rings
    def count_rings(self,image,color_range,min_area):
        native=original(self,image,color_range,min_area)
        if not self.is_browser() or native[1]:return native
        # Only wind/fire have real cloud positive AND near-full negative
        # fixtures so far. Other elements retain their native detector.
        if tuple(color_range.get('r',())) not in ((70,110),(200,230)):
            return native
        adjusted=original(self,normalize_ring_color(image,color_range),color_range,min_area)
        return adjusted if adjusted[1] or adjusted[0]>native[0] else native
    BaseCombatTask.count_rings=count_rings
    BaseCombatTask._cloud_concerto_color=True
