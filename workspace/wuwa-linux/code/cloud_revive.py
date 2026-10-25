"""Ordinary revive consumables first; verified world healing as fallback."""
import re
from contextlib import contextmanager
from cloud_world import verified_world

TITLE=re.compile(r'^选择复苏物品$|^選擇復甦物品$')
CONFIRM=re.compile(r'^确认$|^確認$')
EXIT_CONTEXT=re.compile(r'退出(?:当前|當前)?(?:副本|挑战|挑戰)|[离離]开(?:当前|當前)?副本')


def dungeon_exit_context(boxes):
    texts=[re.sub(r'\s+','',box.name) for box in boxes]
    return bool(EXIT_CONTEXT.search(''.join(texts)) or
                ('确认离开' in texts and '重新挑战' in texts and '确认' in texts))


@contextmanager
def revive_policy(task, entry):
    """Enable the policy only for an explicitly configured boss task."""
    names=('_cloud_use_revive_medicine','_cloud_revive_entry_config',
           '_cloud_revive_medicine_attempts','_cloud_revive_world_heals')
    saved={name:task.__dict__[name] for name in names if name in task.__dict__}
    task._cloud_use_revive_medicine=True
    task._cloud_revive_entry_config=dict(entry)
    task._cloud_revive_medicine_attempts=0
    task._cloud_revive_world_heals=0
    try:yield
    finally:
        for name in names:
            if name in saved:setattr(task,name,saved[name])
            else:task.__dict__.pop(name,None)


def recover_before_entry(task):
    """Recover an existing death dialog before native ensure_main closes it."""
    if not popup(task):return False
    method=medicine_or_heal(task)
    task.reset_to_false(reason='entry death recovered with '+method)
    task.load_chars()
    task._just_entered_boss_realm=True
    task.log_info('CLOUD_REVIVE preflight recovered; retain the current challenge')
    return True


def popup(task):return bool(task.ocr(.18,.14,.50,.25,match=TITLE))


def hp_value(texts):
    names=' '.join(str(getattr(box,'name',box)) for box in texts)
    pairs={(int(a),int(b)) for a,b in re.findall(r'(?<!\d)(\d+)\s*[/／]\s*(\d+)(?!\d)',names)}
    if len(pairs)!=1:return None
    current,total=pairs.pop()
    return (current,total) if total>0 and 0<=current<=total else None


def health(task):
    frame=getattr(task,'frame',None)
    if frame is not None:
        import cv2
        enlarged=cv2.resize(frame,None,fx=3,fy=3,interpolation=cv2.INTER_LINEAR)
        # Keep the original two-fresh-frame full-HP acceptance rule. The
        # former first 2x crop truncated digits; wider crops can lose a
        # faint leading 17. Prefer the real-tested 3x numeric crop.
        tight=hp_value(task.ocr(566/1280,680/720,690/1280,704/720,frame=enlarged))
        margin=hp_value(task.ocr(.39,.92,.66,.995,frame=enlarged))
        return tight if tight is not None else margin
    return hp_value(task.ocr(.40,.93,.65,.99))


def medicine_description(texts):
    text=re.sub(r'\s+','', ''.join(str(getattr(box,'name',box)) for box in texts))
    if re.search('星声|星聲|月相|结晶波片|結晶波片|购买|購買',text):return False
    return bool(re.search(r'恢[复復]意[识識].*(?:回[复復]|恢[复復]).*生命',text))


def medicine_quantity(task,x):
    """Read only a displayed positive inventory number; never infer stock."""
    rect=(x+.012,.432,x+.046,.484)
    boxes=task.ocr(*rect,match=re.compile(r'^\d+$'))
    if not boxes:
        boxes=task.ocr(*rect,match=re.compile(r'^\d+$'),target_height=1440)
    # target_height in the framework only downsizes; it does not enlarge.
    if not boxes and getattr(task,'frame',None) is not None:
        import cv2
        h,w=task.frame.shape[:2]
        a,b,c,d=rect
        crop=task.frame[int(b*h):int(d*h),int(a*w):int(c*w)]
        for scale in (2,4,6):
            enlarged=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_LINEAR)
            boxes=task.ocr(0,0,1,1,match=re.compile(r'^\d+$'),frame=enlarged)
            if boxes:break
    values=[int(box.name) for box in boxes]
    return values[0] if len(values)==1 and 0<values[0]<=9999 else None


def use_medicine(task,target=None):
    """One confirmed consumable use; never click again on uncertain success."""
    if not popup(task):return False
    task.executor.interaction.release_all();task.next_frame()
    # Prefer the stronger ordinary revive item. Quantity must be positive.
    selected=None
    for x in (.597,.500,.403):
        quantity=medicine_quantity(task,x)
        if quantity is None:continue
        task.sleep(.25);task.next_frame()
        if not popup(task):return False
        if medicine_quantity(task,x)==quantity:
            selected=x
            task.log_info(f'CLOUD_REVIVE medicine inventory verified twice quantity={quantity}')
            break
    if selected is None:
        task.log_info('CLOUD_REVIVE no positively read ordinary medicine quantity')
        return False
    task.click_relative(selected,.415,after_sleep=.4)
    task.next_frame()
    if not popup(task) or not medicine_description(task.ocr(.23,.53,.77,.62)):
        task.log_info('CLOUD_REVIVE medicine description not verified; no confirm sent')
        return False
    boxes=task.ocr(.59,.68,.81,.75,match=CONFIRM)
    if len(boxes)!=1:
        task.log_info('CLOUD_REVIVE medicine confirm is unavailable')
        return False
    task.log_info('CLOUD_REVIVE ordinary medicine confirm sent')
    task.click_box(boxes[0],after_sleep=.5)
    if not task.wait_until(lambda:not popup(task),time_out=8,raise_if_not_found=False):
        task.log_info('CLOUD_REVIVE medicine unavailable or on cooldown; no second click')
        return False
    if target is not None:task.send_key(str(target+1),after_sleep=.5)
    def alive():
        task.next_frame();ok,index,count=task.in_team();hp=health(task)
        return bool(ok and count==3 and (target is None or index==target) and hp and hp[0]>0 and not popup(task))
    if not task.wait_until(alive,time_out=6,raise_if_not_found=False):
        task.log_info('CLOUD_REVIVE medicine result lacks a verified living character')
        return False
    task.sleep(.3)
    if not alive():return False
    task.log_info('CLOUD_REVIVE medicine restored a playable character')
    return True


def world_heal_and_reenter(task, *, reenter=True):
    task.executor.interaction.release_all()
    if popup(task):task.close_revive_popup()
    if not reenter:
        def fresh_world():
            task.next_frame()
            return bool(verified_world(task))
        # Identity can become readable before the world HUD finishes loading.
        if not task.wait_until(fresh_world,time_out=8,raise_if_not_found=False):
            texts={box.name.strip() for box in task.ocr(.02,.02,.90,.60)}
            if {'终端','共鸣者','编队'} <= texts or {'終端','共鳴者','編隊'} <= texts:
                task.send_key('esc',after_sleep=.5)
                if not task.wait_until(fresh_world,time_out=8,raise_if_not_found=False):
                    raise RuntimeError('Death recovery: terminal closed but world is not verified')
    if not verified_world(task):
        task.send_key('esc',after_sleep=1)
        def exit_button():
            texts=task.ocr(.18,.25,.86,.82)
            if not dungeon_exit_context(texts):return None
            boxes=task.ocr(.50,.50,.86,.80,match=re.compile(r'^(确认|確認|退出副本|退出挑战|退出挑戰|离开|離開)$'))
            return boxes[0] if len(boxes)==1 else None
        button=task.wait_until(exit_button,time_out=5,raise_if_not_found=False)
        if button is None:raise RuntimeError('Death recovery: dungeon exit is not positively identified')
        task.next_frame();fresh=exit_button()
        if fresh is None:raise RuntimeError('Death recovery: dungeon exit changed before click')
        task.click_box(fresh,after_sleep=1)
        if not task.wait_until(lambda:bool(verified_world(task)),time_out=120,raise_if_not_found=False):
            raise RuntimeError('Death recovery: not verified in the open world')
    def verify_team(timeout):
        for index in range(3):
            task.send_key(str(index+1),after_sleep=.5)
            def full():
                task.next_frame();ok,current,count=task.in_team();hp=health(task)
                revive_open=popup(task)
                task.log_info(f'CLOUD_HEAL_CHECK slot={index+1} team={ok} current={current} count={count} hp={hp} popup={revive_open}')
                return bool(ok and count==3 and current==index and hp and hp[0]==hp[1] and not revive_open)
            def full_pair():
                if not full():return False
                task.sleep(.3)
                return full()
            # A transient second-frame OCR miss retries within the same bound.
            # Every accepted pair still uses two consecutive fresh full readings.
            if not task.wait_until(full_pair,time_out=timeout,raise_if_not_found=False):return index
        return None
    # A reconnect after verified healing must not blindly teleport again.
    # Every slot still requires two full-health observations.
    unverified=verify_team(8)
    if unverified is not None:
        if popup(task):task.close_revive_popup()
        task.log_info('CLOUD_REVIVE verified open world; native healing teleport')
        task.revive_at_tower_and_heal()
        def healed_world():
            task.next_frame()
            return bool(verified_world(task))
        if not task.wait_until(healed_world,time_out=8,raise_if_not_found=False):
            raise RuntimeError('Death recovery: healing did not return to open world')
        unverified=verify_team(8)
        if unverified is not None:
            raise RuntimeError(f'Death recovery: slot {unverified+1} is not confirmed fully healed')
    else:task.log_info('CLOUD_REVIVE all three slots already verified full; no extra teleport')
    if not reenter:
        task.reset_to_false(reason='all three characters verified healed before native entry')
        return
    entry=getattr(task,'_cloud_revive_entry_config',None) or {
        key:task.config.get(key) for key in ('Teleport to Boss','Which Weekly Boss to Teleport','Boss Level')}
    if entry.get('Teleport to Boss') not in ('Weekly Challenge','Boss Challenge'):
        raise RuntimeError('Death recovery: original boss entry is not configured')
    task.reset_to_false(reason='all three characters verified healed')
    # The native material restart temporarily sets Teleport to Boss to No.
    # Re-enter with the captured original target, then restore its restart state.
    saved={key:task.config.get(key) for key in entry}
    try:
        task.config.update(entry)
        task.teleport_to_configured_boss_and_prepare()
    finally:task.config.update(saved)
    task.log_info('CLOUD_REVIVE returned through the original configured boss entry')


@contextmanager
def recovery_navigation(task):
    """Combat sleep checks must not interrupt verified revival/exit/healing navigation."""
    had='skip_combat_check' in task.__dict__
    previous=getattr(task,'skip_combat_check',False)
    task.skip_combat_check=True
    try:yield
    finally:
        if had:task.skip_combat_check=previous
        else:task.__dict__.pop('skip_combat_check',None)


def medicine_or_heal(task,target=None):
    with recovery_navigation(task):return _medicine_or_heal(task,target)


def _medicine_or_heal(task,target=None):
    count=getattr(task,'_cloud_revive_medicine_attempts',0)
    if count<3:
        task._cloud_revive_medicine_attempts=count+1
        if use_medicine(task,target):return 'medicine'
    if getattr(task,'_cloud_revive_world_heals',0)>=1:
        raise RuntimeError('Death recovery: one world healing fallback already used')
    task._cloud_revive_world_heals=1
    world_heal_and_reenter(task)
    return 'world'
