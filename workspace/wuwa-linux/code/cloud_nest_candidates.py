"""Reject known player/HUD false positives; these checks never prove pickup."""
def usable(frame, box):
    import cv2
    import numpy as np
    h,w=frame.shape[:2]
    x1,y1=max(0,int(box.x)),max(0,int(box.y))
    x2,y2=min(w,int(box.x+box.width)),min(h,int(box.y+box.height))
    area=(x2-x1)*(y2-y1)
    if area <= 0:
        return False
    # The controlled character occupies this area in the normal world camera.
    # Close interactions remain available through F/OCR, independently of YOLO.
    overlap=max(0,min(x2,.59*w)-max(x1,.41*w))*max(0,min(y2,.88*h)-max(y1,.32*h))
    if overlap/area >= .6:
        return False
    # Detection boxes can clip the ring's bottom edge; inspect a small margin.
    crop=frame[max(0,y1-8):min(h,y2+8),max(0,x1-8):min(w,x2+8)]
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,np.array([18,65,180]),np.array([40,255,255]))
    contours,hierarchy=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is not None:
        for i,contour in enumerate(contours):
            child=hierarchy[0,i,2]
            outer=cv2.contourArea(contour)
            perimeter=cv2.arcLength(contour,True)
            if child >= 0 and outer > .45*area and perimeter > 0:
                holes=[]
                while child >= 0:
                    holes.append(cv2.contourArea(contours[child]))
                    child=hierarchy[0,child,0]
                # Thin, closed circular overlay (not a filled echo silhouette).
                if 4*np.pi*outer/perimeter**2 > .75 and max(holes)/outer > .7:
                    return False
    return True
