"""Verify native daily closing pages. Unknown states are never completion."""
import hashlib
import json
from pathlib import Path
import re
import time

from cloud_autorun_state import day_key, write_json

REQUIRED = ('mail', 'radio_tasks', 'radio_rewards')
MAIL_EMPTY = re.compile(r'(全部邮件的附件(已经|已)领取完毕|(暂无|没有|无|不存在).*(可领取|可领).*(附件|邮件|奖励))')
ASSETS = {
    'radio_task_tick.png': '69f3180436abbadfddd21e16cc678f92777557d26bc68376c1dc6de4c6af83cc',
    'radio_reward_tick.png': 'e083809916b46a77868a02aa23f2c9c22c0bbbce3f1b97532373084a8f99ce12',
}
TASKS = (('获得1个声骸', '1/1'), ('索拉指南活跃度达到100', '100/100'),
         ('累计消耗180点结晶波片', '180/180'), ('登录游戏', '1/1'))


class DailyClosureError(RuntimeError):
    def __init__(self, step, reason):
        self.step = step
        super().__init__(f'Daily {step} incomplete: {reason}')


def names(boxes):
    return [re.sub(r'\s+', '', b.name) for b in boxes]


def radio_title(task, frame=None):
    # Exclude the circular icon at x=38..62: OCR merged it with the title
    # as "0先约电台" in the 2026-10-07 failure frame. Keep exact matching.
    titles = names(task.ocr(65/1280,22/720,240/1280,72/720,frame=frame))
    found = [s for s in titles if s in ('先约电台', '电台任务')]
    return found[0] if len(found) == 1 else None


def radio_claim_buttons(task, frame):
    import cv2
    # The thin horizontal first character can vanish in whole-page OCR.
    # Read only the free claim button at 2x; exclude the paid unlock button.
    enlarged=cv2.resize(frame,None,fx=2,fy=2,interpolation=cv2.INTER_LINEAR)
    boxes=task.ocr(825/1280,640/720,919/1280,669/720,frame=enlarged)
    matches=[b for b in boxes if re.fullmatch(r'(全部|一键)?领取(经验|奖励)?',
             re.sub(r'\s+','',b.name))]
    for b in matches:
        b.x=round(b.x/2);b.y=round(b.y/2)
        b.width=round(b.width/2);b.height=round(b.height/2)
    return matches


def earned_reward_popup(boxes):
    # The free-level receipt uses the shorter title "获得". Require both
    # the centered title and its blank-area dismissal instruction.
    titles=names([b for b in boxes if 490<=b.x<=750 and 135<=b.y<=220])
    prompts=names([b for b in boxes if 450<=b.x<=800 and 585<=b.y<=675])
    return (any(s in ('获得','获得奖励','获得物品') for s in titles)
            and any(re.fullmatch(r'点击(?:空白处(?:以)?继续|空白区域关闭)',s) for s in prompts))


def free_radio_receipt_confirm(boxes):
    titles=names([b for b in boxes if 490<=b.x<=750 and 135<=b.y<=220])
    if '获得' not in titles or '解锁寰宇频道可额外获得' not in names(boxes):
        return None
    buttons=[b for b in boxes if b.name=='确定' and 700<=b.x<=1000 and 600<=b.y<=690]
    return buttons[0] if len(buttons)==1 else None


def radio_cap_cancel(boxes):
    texts=''.join(names([b for b in boxes if 280<=b.x<=1000 and 280<=b.y<=390]))
    if not (re.search(r'每周可获(?:取)?经验值即将超出上限',texts)
            and '溢出经验无法转换为任何奖励' in texts and '是否继续领取' in texts):
        return None
    buttons=[b for b in boxes if re.sub(r'\s+','',b.name)=='取消'
             and 300<=b.x<=550 and 420<=b.y<=480]
    return buttons[0] if len(buttons)==1 else None


def step_complete(step, proof):
    if proof.get('status')=='VERIFIED':return True
    return (step=='radio_tasks' and proof.get('status')=='SKIPPED_WEEKLY_CAP'
            and proof.get('cap_confirmed') is True and proof.get('cancelled') is True
            and proof.get('experience_claimed') is False
            and [(r.get('task'),r.get('progress')) for r in proof.get('rows',[])]==list(TASKS))


def score(frame, asset, rect):
    import cv2
    path = Path(__file__).resolve().parent/'assets/cloud'/asset
    if hashlib.sha256(path.read_bytes()).hexdigest() != ASSETS[asset]:
        raise RuntimeError('Daily closing marker asset changed')
    if frame.shape[:2] != (720, 1280):
        raise RuntimeError('Daily closing frame dimensions changed')
    x1,y1,x2,y2 = map(int, rect)
    template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    region = cv2.cvtColor(frame[y1:y2,x1:x2], cv2.COLOR_BGR2GRAY)
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        raise RuntimeError('Daily closing marker region invalid')
    return float(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max())


def radio_tasks_evidence(frame, boxes, *, skip_experience=False):
    if '电台任务' not in names(boxes) or '晨间放送' not in names(boxes):
        raise DailyClosureError('radio_tasks', 'daily radio page not verified')
    rows = []
    for label, count in TASKS:
        found = [b for b in boxes if re.sub(r'\s+', '', b.name) == label]
        if len(found) != 1:
            raise DailyClosureError('radio_tasks', f'task unreadable: {label}')
        b = found[0]
        counts = names([p for p in boxes if 300 <= p.x < 580 and b.y+20 <= p.y <= b.y+65
                        and re.fullmatch(r'\d+/\d+', re.sub(r'\s+', '', p.name))])
        if counts != [count]:
            raise DailyClosureError('radio_tasks', f'task not complete: {label}')
        tick = score(frame, 'radio_task_tick.png', (1100,b.y,1210,b.y+75))
        if tick < .90 and not skip_experience:
            raise DailyClosureError('radio_tasks', f'experience not verified claimed: {label}')
        rows.append(dict(task=label, progress=count, claimed_score=tick))
    return dict(status='SKIPPED_WEEKLY_CAP' if skip_experience else 'VERIFIED', rows=rows)


def radio_rewards_evidence(frame, boxes):
    texts = names(boxes)
    if '先约电台' not in texts or '大众频道' not in texts:
        raise DailyClosureError('radio_rewards', 'free reward page not verified')
    levels = [int(b.name) for b in boxes if 155 <= b.x <= 235 and 100 <= b.y <= 190
              and re.fullmatch(r'\d+', b.name)]
    if len(levels) != 1 or not 1 <= levels[0] <= 70:
        raise DailyClosureError('radio_rewards', 'current radio level unreadable')
    columns = [b for b in boxes if 280 <= b.x <= 1000 and 220 <= b.y <= 255
               and b.name == str(levels[0])]
    if len(columns) != 1:
        raise DailyClosureError('radio_rewards', 'current free reward not visible')
    if any(re.fullmatch(r'(全部|一键)?领取(奖励)?', s) for s in texts):
        raise DailyClosureError('radio_rewards', 'claimable reward still visible')
    x = columns[0].x + columns[0].width/2
    tick = score(frame, 'radio_reward_tick.png', (max(280,x-45),275,min(1030,x+45),345))
    if tick < .90:
        raise DailyClosureError('radio_rewards', 'current free reward not verified claimed')
    return dict(status='VERIFIED', level=levels[0], current_free_reward_score=tick,
                batch_claim_button_absent=True)


def complete(closure, expected_day):
    return (isinstance(closure, dict) and closure.get('complete') is True
            and closure.get('game_day') == expected_day
            and all(step_complete(s,closure.get('steps', {}).get(s, {})) for s in REQUIRED))


def install(task, output, *, radio_rewards_only=False, previous_closure=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    day = day_key()
    result = dict(game_day=day, complete=False, steps={})
    prior_path=output/'daily-closure.json'
    if prior_path.exists():
        prior=json.loads(prior_path.read_text(encoding='utf-8'))
        if prior.get('game_day')==day:
            for step in ('mail','radio_tasks'):
                proof=prior.get('steps',{}).get(step,{})
                if step_complete(step,proof):result['steps'][step]=dict(proof)
    if radio_rewards_only:
        if not isinstance(previous_closure,dict) or previous_closure.get('game_day')!=day:
            raise DailyClosureError('radio_rewards','same-day prior proof required')
        for step in ('mail','radio_tasks'):
            proof=previous_closure.get('steps',{}).get(step,{})
            if not step_complete(step,proof):
                raise DailyClosureError(step,'previous step not verified')
            result['steps'][step]=dict(proof)
    task._cloud_daily_closure = result
    log_info = task.log_info
    def save():
        result['complete'] = all(step_complete(s,result['steps'].get(s, {})) for s in REQUIRED)
        result['verified_at'] = time.time()
        write_json(output/'daily-closure.json', result)
    def check():
        if day_key() != day: raise RuntimeError('Daily refreshed during closing claims')
    def snap(label):
        import cv2
        path=output/f'{time.time_ns()}-{label}.png'
        cv2.imwrite(str(path), task.frame)
        return str(path)
    def read(reward=False):
        check(); task.next_frame()
        frame=task.frame
        boxes=task.ocr(0,0,1,1,frame=frame)
        boxes=[b for b in boxes if not (b.x<320 and b.y<90)]
        boxes+=task.ocr(65/1280,22/720,240/1280,72/720,frame=frame)
        if reward:
            # Decorative backgrounds can merge titles in full-screen OCR.
            # Read the known title and free-channel label on the same frame.
            boxes=[b for b in boxes if not (b.x<320 and b.y<90)
                   and not (150<=b.x<275 and 335<=b.y<390)]
            boxes+=task.ocr(65/1280,22/720,240/1280,72/720,frame=frame)
            boxes+=task.ocr(.12,.47,.22,.54,frame=frame)
            boxes+=radio_claim_buttons(task,frame)
            # Whole-page OCR misses a solitary level 1 inside the circular badge.
            import cv2
            boxes=[b for b in boxes if not (155<=b.x<=235 and 100<=b.y<=190)]
            boxes+=task.ocr(185/1280,140/720,225/1280,177/720,frame=frame,
                frame_processor=lambda crop:cv2.resize(crop,None,fx=3,fy=3))
        return boxes
    def wait_title(title):
        check()
        if title in ('先约电台','电台任务'):
            if not task.wait_until(lambda: radio_title(task)==title,time_out=8):
                raise DailyClosureError(title, 'page title unreadable')
            return
        if not task.wait_ocr(0,0,.25,.15,match=re.compile('^'+title+'$'),time_out=8):
            raise DailyClosureError(title, 'page title unreadable')
    def radio_tab(y, title):
        for _ in range(2):
            # A click can be ignored while the just-opened page is animating.
            # Retry only on a positively identified radio page, never in the world.
            check(); task.next_frame()
            observed=radio_title(task,task.frame)
            # Brief read-only settling; an unknown screen never authorizes input.
            for settle in range(2):
                if observed is not None:break
                task.sleep(.3);check();task.next_frame()
                observed=radio_title(task,task.frame)
            if observed==title:return
            if observed is None:
                raise DailyClosureError(title, 'radio page lost before tab click')
            task.click_relative(.04,y,after_sleep=1.5)
            if task.wait_until(lambda: radio_title(task)==title,time_out=4):return
        raise DailyClosureError(title, 'radio tab did not respond to two verified clicks')
    def terminal():
        cancel_cap()
        task.ensure_main(time_out=60)
        for _ in range(3):
            check(); task.back(after_sleep=.8)
            if task.ocr(0,0,.22,.13,match=re.compile('^终端$')): return
        raise DailyClosureError('menu', 'terminal not verified; no blind menu clicks')
    def verified(step, evidence):
        result['steps'][step] = dict(evidence, image=snap(step), verified_at=time.time())
        save()
    def stable(proof):
        first=None;last_error=None
        for _ in range(4):
            boxes=read(reward=proof is radio_rewards_evidence)
            try:
                second=proof(task.frame,boxes)
            except DailyClosureError as exc:
                last_error=exc;first=None;task.sleep(.3);continue
            if first is not None:break
            first=second;task.sleep(.3)
        else:
            raise last_error or RuntimeError('Daily closing evidence did not stabilize')
        if first.keys()!=second.keys(): raise RuntimeError('Daily closing page changed between reads')
        if first.get('level')!=second.get('level') or first.get('rows') and [r['progress'] for r in first['rows']]!=[r['progress'] for r in second['rows']]:
            raise RuntimeError('Daily closing progress changed between reads')
        # Never treat one transient frame as completion.
        return second
    def claim_buttons():
        task.next_frame()
        focused=radio_claim_buttons(task,task.frame)
        if focused:return focused
        boxes=task.ocr(.45,.84,.97,.96,frame=task.frame)
        return [b for b in boxes if re.fullmatch(r'(全部|一键)?领取(经验|奖励)?', re.sub(r'\s+','',b.name))]
    cap={}
    def cancel_cap():
        first=radio_cap_cancel(read())
        if first is None:return False
        task.sleep(.3)
        second=radio_cap_cancel(read())
        if second is None:raise DailyClosureError('radio_tasks','cap popup changed before cancellation')
        cap.update(cap_confirmed=True,experience_claimed=False,image=snap('radio-cap-before-cancel'))
        task.click_box(second,after_sleep=1)
        wait_title('电台任务')
        cap.update(cancelled=True,verified_at=time.time())
        write_json(output/'radio-cap-skip.json',cap)
        return True
    task._cloud_cancel_radio_cap=cancel_cap
    def dismiss_reward():
        if cancel_cap():return True
        boxes=read()
        confirm=free_radio_receipt_confirm(boxes)
        if confirm is not None:
            write_json(output/f'{time.time_ns()}-free-radio-receipt.json',
                       dict(image=snap('free-radio-receipt'),texts=names(boxes)))
            task.click_box(confirm,after_sleep=1)
            return True
        if not (any(s in ('获得奖励','获得物品') for s in names(boxes))
                or earned_reward_popup(boxes)): return False
        write_json(output/f'{time.time_ns()}-received-reward.json',
                   dict(image=snap('received-reward'),texts=names(boxes)))
        # A positively recognized reward popup only. Never purchase/select items.
        task.click_relative(.5,.9,after_sleep=1)
        return True
    def mail():
        if result['steps'].get('mail',{}).get('status')=='VERIFIED':return
        try:
            terminal(); task.click(.64,.95,after_sleep=1); wait_title('邮件')
            for _ in range(2):
                check()
                buttons=task.ocr(0,.85,.4,.97,match=re.compile('^全部领取$'))
                if len(buttons)!=1: raise DailyClosureError('mail','claim-all unreadable')
                task.click_box(buttons[0],after_sleep=.1)
                observed=[]
                def notice():
                    observed[:] = read()
                    texts=names(observed)
                    return (any(MAIL_EMPTY.search(s) for s in texts)
                            or any(s in ('获得奖励','获得物品') for s in texts)
                            or earned_reward_popup(observed))
                if not task.wait_until(notice,time_out=4):
                    raise DailyClosureError('mail','neither received rewards nor explicit empty response')
                texts=names(observed)
                if any(MAIL_EMPTY.search(s) for s in texts):
                    verified('mail',dict(status='VERIFIED',source='explicit_no_claimable_attachments'))
                    # Close the verified mail page before generic world recovery:
                    # its attachment grid can match the native monthly-card popup.
                    wait_title('邮件')
                    task.back(after_sleep=1)
                    task.ensure_main(); return
                dismiss_reward(); wait_title('邮件')
            raise DailyClosureError('mail','could not verify no remaining attachments')
        except Exception as exc:
            result['steps']['mail']=dict(status='FAILED',reason=str(exc),image=snap('mail-failed'));save();raise
    def radio():
        active_step='radio_rewards' if radio_rewards_only else 'radio_tasks'
        try:
            terminal()
            boxes=task.ocr(.65,.2,.85,.34,match=re.compile('^先约电台$'))
            if len(boxes)!=1: raise DailyClosureError('radio_tasks','terminal radio entry unreadable')
            task.click_box(boxes[0],after_sleep=1); wait_title('先约电台')
            if not radio_rewards_only and not step_complete('radio_tasks',result['steps'].get('radio_tasks',{})):
                radio_tab(.3,'电台任务')
                # Original task tab. Explicitly select daily section before checking all four rows.
                task.click_relative(.15,.35,after_sleep=.5)
                before=read()
                if '电台任务' not in names(before) or '晨间放送' not in names(before):
                    raise DailyClosureError('radio_tasks','daily section not confirmed before claims')
                write_json(output/'radio-tasks-before.json',dict(image=snap('radio-tasks-before'),
                    texts=names(before)))
                buttons=claim_buttons()
                if len(buttons)>1: raise DailyClosureError('radio_tasks','ambiguous claim-all')
                if buttons and not cap:
                    task.click_box(buttons[0],after_sleep=1); dismiss_reward(); wait_title('电台任务')
                # If this client exposes per-row claims instead of a batch button,
                # only the four visible daily rows are eligible for this fallback.
                for _ in range(4):
                    if cap:break
                    check();task.next_frame()
                    rows=task.ocr(.84,.32,.96,.79,match=re.compile('^领取$'))
                    if not rows:break
                    task.click_box(rows[0],after_sleep=1);dismiss_reward();wait_title('电台任务')
                if cap:
                    proof=stable(lambda frame,boxes:radio_tasks_evidence(frame,boxes,skip_experience=True))
                    verified('radio_tasks',dict(proof,**{k:v for k,v in cap.items() if k!='image'},
                        cap_image=cap['image'],source='user_authorized_skip_on_weekly_experience_cap'))
                else:verified('radio_tasks',stable(radio_tasks_evidence))
            active_step='radio_rewards'
            radio_tab(.17,'先约电台')
            before=read(reward=True)
            if '先约电台' not in names(before) or '大众频道' not in names(before):
                raise DailyClosureError('radio_rewards','free channel not confirmed before claims')
            write_json(output/'radio-rewards-before.json',dict(image=snap('radio-rewards-before'),
                texts=names(before)))
            buttons=claim_buttons()
            if len(buttons)>1: raise DailyClosureError('radio_rewards','ambiguous claim-all')
            if buttons:
                task.click_box(buttons[0],after_sleep=1); dismiss_reward(); wait_title('先约电台')
            verified('radio_rewards',stable(radio_rewards_evidence))
            task.ensure_main()
        except Exception as exc:
            step=getattr(exc,'step',active_step)
            if step not in ('radio_tasks','radio_rewards'): step=active_step
            result['steps'][step]=dict(status='FAILED',reason=str(exc),image=snap(step+'-failed'));save();raise
    def guarded_log(message, *args, **kwargs):
        if message == 'Daily Task Completed': return
        return log_info(message,*args,**kwargs)
    task.claim_mail=mail
    task.claim_battle_pass=radio
    task.log_info=guarded_log
    return result, log_info
