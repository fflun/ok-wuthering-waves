"""Server-only supplement for digits lost by the native white-text filter.

Read the same frame at 3x scale; never override a native positive reading.
Only a complete decimal, confidence >= .95, inside the original CD strip
and an unambiguous native skill column can supplement a missing result.
"""
import json, os, re, time
from pathlib import Path

DECIMAL = re.compile(r'\d{1,2}\.\d')

def slot(box, width):
    if box.x < width * .86: return 'resonance'
    if box.x > width * .91: return 'liberation'
    return 'echo'

def select_supplement(native, raw, width, height):
    occupied = {slot(b, width) for b in native}
    groups = {}
    for b in raw:
        name = str(b.name).strip()
        if (not DECIMAL.fullmatch(name) or not .1 <= float(name) <= 99.9
                or b.confidence < .95): continue
        if not (width*.82 <= b.x < b.x+b.width <= width*.97+1
                and height*.86 <= b.y < b.y+b.height <= height*.93+1): continue
        s = slot(b, width)
        # Refuse boxes crossing either native classification boundary.
        if any(b.x <= width*c <= b.x+b.width for c in (.86,.91)): continue
        if s not in occupied: groups.setdefault(s, []).append(b)
    return [v[0] for v in groups.values() if len(v) == 1]

def supplement(task, native, frame):
    if frame is None or frame.shape[:2] != (720,1280): return native
    if len({slot(b,1280) for b in native}) == 3: return native
    import cv2
    from ok import Box
    # Native target_height only downsizes. Explicitly enlarge this strip and
    # pass scale_factor=3 to its existing OCR mapper, preserving screen coords.
    region=Box(1050,619,192,51)
    crop=cv2.resize(frame[619:670,1050:1242],None,fx=3,fy=3)
    raw,_ = task.ocr_fun('default')(region,crop,DECIMAL,3,.95,'default')
    added = select_supplement(native, raw,1280,720)
    if added:
        detail = [{'slot':slot(b,1280),'text':b.name,'confidence':b.confidence} for b in added]
        task.log_info('CLOUD_CD_COLOR_SUPPLEMENT '+json.dumps(detail))
        count = getattr(task,'_cloud_cd_evidence_count',0)
        folder = os.environ.get('OKWW_DAILY_OUTPUT')
        if folder and count < 8:
            import cv2
            out=Path(folder)/'cooldown-evidence';out.mkdir(exist_ok=True,parents=True)
            stem=str(time.time_ns())
            cv2.imwrite(str(out/(stem+'.png')),frame[619:670,1050:1242])
            (out/(stem+'.json')).write_text(json.dumps({'at':time.time(),'readings':detail}))
            task._cloud_cd_evidence_count=count+1
    return [*native,*added]
