"""Exact-item, single-use food receipts. UI actions require observed anchors."""
import hashlib
import json
import re
import time
from pathlib import Path

from cloud_autorun_state import day_key, write_json

FOOD='糖醋里脊'


def food_cooldown(boxes):
    values=[]
    for box in boxes:
        match=re.fullmatch(r'(\d{1,2}(?:\.\d)?)\s*[sS秒]',box.name.strip())
        if match:values.append(float(match.group(1)))
    return values[0] if len(values)==1 and 0<values[0]<=60 else None


def food_use_confirmed(before,after,cooldown_confirmed):
    # Either positive signal is sufficient; contradictory quantity is not.
    if after is not None and (type(after) is not int or after not in (before,before-1)):
        return False
    return after==before-1 or cooldown_confirmed is True


class FoodUnconfirmed(RuntimeError):
    pass


def food_duration(text):
    text=re.sub(r'\s+','',text)
    matches=re.findall(r'(?:持续|持续时间[:：]?)(\d+)(分钟|秒)',text)
    values={int(n)*(60 if unit=='分钟' else 1) for n,unit in matches}
    return next(iter(values)) if len(values)==1 and 60<=next(iter(values))<=7200 else None


class FoodReceipt:
    def __init__(self,path,account,session,resume_session=None):
        self.path=Path(path)
        self.scope=dict(game_day=day_key(),account=hashlib.sha256(account.encode()).hexdigest(),item=FOOD)
        self.session=session
        self.resume_session=resume_session
        self.data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else dict(self.scope,uses=[],pending=None)
        if any(self.data.get(k)!=v for k,v in self.scope.items()):
            if self.data.get('pending'):raise FoodUnconfirmed('Unresolved food use belongs to another scope')
            self.data=dict(self.scope,uses=[],pending=None)
    def check(self):
        if day_key()!=self.scope['game_day']:raise FoodUnconfirmed('Game refresh during food preparation')
        if self.data.get('pending'):raise FoodUnconfirmed('Previous food use unresolved; do not consume again')
    def active(self,now=None):
        self.check();now=time.time() if now is None else now
        uses=self.data['uses']
        return bool(uses and uses[-1]['session'] in (self.session,self.resume_session) and
                    uses[-1]['used_at']<=now<uses[-1]['expires_at']-60)
    def begin(self,name,before,duration,image):
        self.check()
        if name!=FOOD or type(before) is not int or before<1 or not duration or not 60<=duration<=7200:
            raise FoodUnconfirmed('Food identity, inventory or duration unverified')
        if len(self.data['uses'])>=3:raise FoodUnconfirmed('Three food uses per game day limit reached')
        self.data['pending']=dict(item=name,before=before,duration=duration,image=image,started_at=time.time(),session=self.session)
        write_json(self.path,self.data)
    def finish(self,after,effect_confirmed,image):
        p=self.data.get('pending')
        if not p or not food_use_confirmed(p['before'],after,effect_confirmed):
            raise FoodUnconfirmed('Food use requires one-item decrease or newly observed cooldown')
        if day_key()!=self.scope['game_day']:raise FoodUnconfirmed('Game refreshed after food use')
        now=time.time()
        result=dict(p,after=after,used_at=now,expires_at=p['started_at']+p['duration'],effect_confirmed=True,after_image=image)
        self.data['uses'].append(result);self.data['pending']=None;write_json(self.path,self.data)
        return result


def selected_food(boxes):
    texts=[re.sub(r'\s+','',b.name) for b in boxes]
    if FOOD not in texts:return None
    quantities=[int(m.group(1)) for t in texts if (m:=re.fullmatch(r'拥有(\d+)',t))]
    description=''.join(texts)
    duration=food_duration(description)
    if len(quantities)!=1 or duration is None or '声骸吸收概率提升50%' not in description:
        return None
    return quantities[0],duration


def prepare(task,output,*,receipt_path=None,session=None):
    """Inspect exact food, use once, accept inventory decrease OR new cooldown."""
    import cv2
    import os
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    state=Path(__file__).resolve().parent.parent/'okww-cloud-session/background'
    def snap(label):
        path=output/f'{time.time_ns()}-food-{label}.png';cv2.imwrite(str(path),task.frame);return str(path)
    def event(label,**data):
        with (output/'food-events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(at=time.time(),event=label,**data),ensure_ascii=False)+'\n')
    def title():return ''.join(b.name for b in task.ocr(0,0,.28,.10))
    def read_selected():return selected_food(task.ocr(.685,.10,.98,.50))
    task.ensure_main(time_out=30)
    account=re.findall(r'(?<!\d)\d{9}(?!\d)',''.join(b.name for b in task.ocr(.8,.96,1,1)))
    if len(account)!=1:raise FoodUnconfirmed('Food account not identified')
    receipt=FoodReceipt(receipt_path or state/'food-receipt.json',account[0],
                        session if session is not None else os.environ.get('OKWW_FULL_RUN_ID',''),
                        resume_session=os.environ.get('OKWW_FOOD_RESUME_SESSION'))
    if receipt.active():
        event('food_effect_retained',expires_at=receipt.data['uses'][-1]['expires_at'])
        return True  # ensure_main has closed the book; caller must reselect it.
    # A missing/unreadable optional food never blocks combat. Keep the
    # per-session decision so a retry does not keep reopening the inventory.
    receipt.check()
    if any(s.get('session')==receipt.session for s in receipt.data.get('skipped_sessions',[])):
        event('food_skip_retained',session=receipt.session)
        return False
    def skip_food(reason):
        receipt.check()  # A prior use pending is not a missing-item decision.
        image=snap('skipped')
        task.ensure_main(time_out=30)
        receipt.data.setdefault('skipped_sessions',[]).append(dict(
            session=receipt.session,at=time.time(),reason=reason,image=image))
        write_json(receipt.path,receipt.data)
        event('food_skipped',reason=reason,image=image,used=False)
        return False
    task.send_key('b',after_sleep=1.5)
    if not re.search(r'(武器|声骸|补给|材料|任务|贵重|道具)',title()):
        raise FoodUnconfirmed('Inventory not positively identified: '+snap('unknown-inventory'))
    task.click_relative(.052,.428,after_sleep=1)
    if '补给' not in title():raise FoodUnconfirmed('Supplies category not confirmed')
    asset=Path(__file__).resolve().parent/'assets/cloud/food-tangcu.png'
    if hashlib.sha256(asset.read_bytes()).hexdigest()!='62f2b9f80ff7f7e6c59fb9533004a27938b838afec987683fd284cf5647befae':
        raise FoodUnconfirmed('Food icon template changed')
    unselected=asset.with_name('food-tangcu-unselected.png')
    if hashlib.sha256(unselected.read_bytes()).hexdigest()!='cc72a58f8b66ca945fe096aaa5b68e401887e811f72698bb387ff4078d09d088':
        raise FoodUnconfirmed('Unselected food icon template changed')
    templates=[cv2.imread(str(asset)),cv2.imread(str(unselected))]
    if any(t is None for t in templates):raise FoodUnconfirmed('Food icon template unreadable')
    # Inventory remembers its scroll position. Return toward the start first.
    for _ in range(3):
        task.swipe_relative(.6,.30,.6,.78,duration=.5);task.sleep(.4)
        if '补给' not in title():raise FoodUnconfirmed('Food list page lost while returning to top')
    seen=set();found=None
    for page in range(5):
        task.next_frame();frame=task.frame
        if frame.shape[:2]!=(720,1280):raise FoodUnconfirmed('Food frame geometry changed')
        crop=frame[85:610,110:810]
        candidates=[]
        for template in templates:
            _,value,_,position=cv2.minMaxLoc(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED))
            candidates.append((value,position,template))
        value,position,template=max(candidates,key=lambda candidate:candidate[0])
        event('food_search_page',page=page,score=float(value),image=snap('search'))
        if value>=.70:
            task.click_relative((110+position[0]+template.shape[1]/2)/1280,
                                (85+position[1]+template.shape[0]/2)/720,after_sleep=.5)
            first=read_selected();task.sleep(.3);task.next_frame();second=read_selected()
            if first and first==second:found=first;break
            return skip_food('Food icon matched but exact identity/quantity not verified')
        signature=hashlib.sha256(crop.tobytes()).hexdigest()
        if signature in seen:break
        seen.add(signature);task.swipe_relative(.6,.70,.6,.32,duration=.5);task.sleep(.5)
        if '补给' not in title():raise FoodUnconfirmed('Food list page lost')
    if found is None:return skip_food('Sugar-vinegar pork not found; no purchase/substitution')
    before,duration=found
    if before<1:return skip_food('Sugar-vinegar pork inventory empty')
    icon_rect=((100+position[0])/1280,(75+position[1])/720,
               (120+position[0]+template.shape[1])/1280,(95+position[1]+template.shape[0])/720)
    if food_cooldown(task.ocr(*icon_rect)) is not None:
        return skip_food('Selected food already cooling down; no extra use')
    buttons=task.ocr(.78,.87,.98,.97,match=re.compile('^使用$'))
    if len(buttons)!=1:return skip_food('Food Use button not positively identified')
    image=snap('before');receipt.begin(FOOD,before,duration,image)
    event('food_use_started',item=FOOD,before=before,duration=duration,image=image)
    task.click_box(buttons[0],after_sleep=.1)
    success=False;after=None
    for _ in range(18):
        task.next_frame()
        current=read_selected()
        after=current[0] if current else None
        cooldown=food_cooldown(task.ocr(*icon_rect))
        success=cooldown is not None
        if food_use_confirmed(before,after,success):break
        task.sleep(.15)
    final=snap('after')
    if not food_use_confirmed(before,after,success):
        event('food_use_unconfirmed',before=before,after=after,cooldown_confirmed=success,image=final)
        raise FoodUnconfirmed('Food result unconfirmed; pending receipt prevents another use: '+final)
    receipt.finish(after,success,final);event('food_use_verified',before=before,after=after,
        confirmation='inventory_decrease' if after==before-1 else 'new_cooldown',image=final)
    task.ensure_main(time_out=30)
    return True
