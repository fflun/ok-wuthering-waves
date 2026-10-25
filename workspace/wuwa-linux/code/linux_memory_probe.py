import runpy,os
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
root=Path(__file__).resolve().parent
os.chdir(root)
state=runpy.run_path(str(root/'linux_preflight.py'))
app=state['app']
from ok import og
font=next((root.parent/'fonts').rglob('*.ttc'))
image=Image.new('RGB',(1280,720),'white')
ImageDraw.Draw(image).text((90,90),'领取奖励',font=ImageFont.truetype(str(font),42),fill='black')
frame=np.array(image)[:,:,::-1].copy()
result=app.task_executor.ocr_lib().ocr(frame)
assert '领取奖励' in str(result),result
og.my_app.yolo_model.detect(frame)
print('OCR_CHINESE_AND_ECHO_MODEL_PASS',flush=True)
runpy.run_path(str(root/'linux_dynamic_probe.py'))
