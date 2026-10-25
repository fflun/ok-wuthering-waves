"""Observe native daily activity and claimed markers; never replace combat."""
import hashlib
import json
from pathlib import Path
import re
import time

from cloud_autorun_state import day_key


def activity_value(title_texts, point_texts):
    names=[str(getattr(box,'name',box)).strip() for box in title_texts]
    if not any(re.fullmatch('活[跃躍]行[迹跡]',name) for name in names):
        raise RuntimeError('Daily activity page title is unreadable')
    values=[int(str(getattr(box,'name',box)).strip()) for box in point_texts
            if re.fullmatch(r'\d+',str(getattr(box,'name',box)).strip())]
    if len(values)!=1 or not 0<=values[0]<=300:
        raise RuntimeError('Daily activity value is unreadable or ambiguous')
    return values[0]


def claimed_tick_scores(frame):
    import cv2
    asset=Path(__file__).resolve().parent/'assets/cloud/garden_claimed_tick.png'
    if hashlib.sha256(asset.read_bytes()).hexdigest()!='e3706786f86173b88ce3eed281d999346e9ab171cf10452b1ad0d53a4a55826e':
        raise RuntimeError('Claimed marker asset changed')
    if frame.shape[:2]!=(720,1280):raise RuntimeError('Daily reward frame size changed')
    # Inner check stroke excludes circle shading, which differs by milestone.
    template=cv2.imread(str(asset),cv2.IMREAD_GRAYSCALE)[7:21,8:23]
    scores=[]
    for x in (503,673,841,1011,1181):
        region=cv2.cvtColor(frame[622:656,x-18:x+18],cv2.COLOR_BGR2GRAY)
        scores.append(float(cv2.matchTemplate(region,template,cv2.TM_CCOEFF_NORMED).max()))
    return scores


def scrollbar_grip(frame):
    if frame.shape[:2]!=(720,1280):raise RuntimeError('Daily stamina progress unreadable: scrollbar frame dimensions changed')
    import numpy as np
    crop=frame[128:576,1246:1251,:3].astype('int16')
    rows=((crop.min(axis=2)>180)&(crop.max(axis=2)-crop.min(axis=2)<25)).sum(axis=1)>=2
    indices=np.flatnonzero(rows)
    runs=[]
    for group in np.split(indices,np.where(np.diff(indices)>1)[0]+1):
        if 40<=len(group)<=300:runs.append(group)
    if len(runs)!=1:raise RuntimeError('Daily stamina progress unreadable: scrollbar thumb unreadable or ambiguous')
    return (128+(int(runs[0][0])+int(runs[0][-1]))/2)/720

def run_tacet_daily(native, *, material, recheck, check_day, assert_clear,
                    recover, revived_error, used_stamina=0, config=None,
                    max_recoveries=2):
    """Continue only a verified revival; reread daily spending before re-entry."""
    for attempt in range(max_recoveries+1):
        check_day();assert_clear()
        if used_stamina>=180:return
        recover()
        check_day();assert_clear()
        material._cloud_material_exit=None
        try:
            return native(daily=True,used_stamina=used_stamina,config=config)
        except revived_error:
            material.executor.interaction.release_all()
            check_day();assert_clear()
            if attempt>=max_recoveries:
                raise RuntimeError('Daily Tacet revival continuation limit reached')
            # The original recovery already returned to the world. Never use
            # pre-death counters or mark that fight as a completed claim.
            used_stamina,ready=recheck()
            if ready or used_stamina>=180:return
            material.log_info(f'CLOUD_DAILY_REVIVE recheck used={used_stamina}; native re-entry')


def ensure_activity_tab(task):
    """One reversible tab correction after a positively identified material page."""
    def title():
        task.next_frame()
        return {str(getattr(box,'name',box)).strip() for box in task.ocr(0,0,.32,.10)}
    if any(re.fullmatch('活[跃躍]行[迹跡]',name) for name in title()):return False
    def material_tab():
        if '素材获取' not in title():return None
        labels={str(getattr(box,'name',box)).strip() for box in task.ocr(.08,.12,.36,.90)}
        if len(labels & {'模拟领域','凝素领域','讨伐强敌','战歌重奏','无声清剿','残象聚落'})<3:return None
        # Use the unchanged native guidebook locator and threshold. Restrict
        # the observed activity icon to the top left tab, never a list action.
        icon=task.find_one('gray_book_quest',box='box_gray_book',threshold=.3)
        if icon is None or not (20<=icon.x<=75 and 90<=icon.y<=150):return None
        return icon
    first=material_tab()
    if first is None:return False
    task.sleep(.3);second=material_tab()
    if second is None or abs(first.x-second.x)>3 or abs(first.y-second.y)>3:
        raise RuntimeError('Daily guidebook tab changed before correction')
    task.click_box(second,after_sleep=1.5)
    if not any(re.fullmatch('活[跃躍]行[迹跡]',name) for name in title()):
        raise RuntimeError('Daily activity tab correction did not return its title')
    return True


def install(task,output,probe=False,resume=False,pending_claim=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    expected_day=day_key()
    native_run,native_open_unverified=task.run,task.open_daily
    def native_open():
        result=native_open_unverified()
        ensure_activity_tab(task)
        return result
    closure = completion_log = None
    if not probe:
        from cloud_daily_closure import install as install_closure
        closure,completion_log=install_closure(task,output)
    def check_day():
        if day_key()!=expected_day:raise RuntimeError('Daily refreshed during execution')
    def read():
        import cv2
        check_day();task.next_frame()
        # A single small gold digit (notably 0) may yield no text at 720p.
        # Scale only this OCR crop; retain strict unique-value/page validation.
        points=activity_value(task.ocr(0,0,.32,.10),
            task.ocr(.19,.80,.30,.90,
                frame_processor=lambda crop:cv2.resize(crop,None,fx=3,fy=3),log=True))
        scores=claimed_tick_scores(task.frame)
        return dict(activity=points,verified_rewards=sum(score>=.90 for score in scores),tick_scores=scores)
    def observe():
        import cv2
        first=None
        for attempt in range(6):
            try:second=read()
            except RuntimeError as exc:
                if not str(exc).startswith('Daily activity'):raise
                cv2.imwrite(str(output/f'{time.time_ns()}-activity-unreadable.png'),task.frame)
                first=None
            else:
                if first is not None and (first['activity'],first['verified_rewards'])==(second['activity'],second['verified_rewards']):
                    break
                first=second
            task.sleep(.3)
        else:raise RuntimeError('Daily activity not stable after six fresh reads')
        path=output/f'{time.time_ns()}-daily-verification.png'
        cv2.imwrite(str(path),task.frame)
        result=dict(second,game_day=expected_day,verified_at=time.time(),image=str(path),
                    complete=second['activity']>=100 and second['verified_rewards']==5)
        (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
    def opened():
        used,_=native_open()
        observed=observe()
        # A positively read activity value is required before deciding to farm.
        if observed['activity']<100:
            progress=task.ocr(.1,.1,.5,.75,match=re.compile(r'^\d+/180$'))
            values={int(box.name.split('/')[0]) for box in progress}
            if not values:
                # Completed tasks move down the activity list. Look on both
                # ends before interpreting a missing counter as unknown.
                for end in (.77,.77,.77,.21):
                    check_day()
                    titles=[getattr(b,'name',str(b)) for b in task.ocr(0,0,.32,.10)]
                    if '活跃行迹' not in titles:break
                    # The streamed game list does not consistently accept wheel
                    # events. Drag its visible scrollbar, as native nest navigation
                    # does, and retain the actual post-navigation frame.
                    task.next_frame()
                    start=scrollbar_grip(task.frame)
                    task.swipe_relative(.975,start,.975,end,duration=.6)
                    task.sleep(.7);task.next_frame()
                    import cv2
                    cv2.imwrite(str(output/f'{time.time_ns()}-stamina-list.png'),task.frame)
                    progress=task.ocr(.1,.1,.65,.83,match=re.compile(r'^\d+/180$'))
                    values={int(box.name.split('/')[0]) for box in progress}
                    if values:break
            if len(values)!=1 or not 0<=next(iter(values))<=180:
                raise RuntimeError('Daily stamina progress is unreadable; refuse to repeat farming')
            used=values.pop()
        return used,observed['activity']>=100
    def run():
        check_day()
        if probe:
            task.ensure_main(time_out=60);native_open()
        else:
            if resume:
                # Collect already-earned task points before native run decides
                # whether stamina farming is still needed.
                task.ensure_main(time_out=60);native_open();observe()
                task.claim_daily()
            native_run();native_open()
        result=observe();task._cloud_daily_verification=result
        if not probe and not result['complete']:
            raise RuntimeError('Daily ended without verified 100 activity and all five claimed rewards')
        if not probe:
            from cloud_daily_closure import complete
            if not complete(closure,expected_day):
                raise RuntimeError('Daily closing claims incomplete; mail and both radio pages are mandatory')
            task._cloud_daily_verification=dict(result,all_daily_complete=True,
                                                closure=closure)
        # observe() positively identified the activity page. Close it explicitly;
        # native generic recovery can mistake the claimed reward row for a monthly card.
        task.back(after_sleep=1)
        task.ensure_main(time_out=10)
        if not probe:completion_log('Daily Task Completed',notify=True)
    task.open_daily=opened
    task.run=run
    if not probe and task.is_browser():
        from src.task.ForgeryTask import ForgeryTask
        from cloud_daily_death_watch import install as install_death_watch
        install_death_watch(task.get_task_by_class(ForgeryTask))
        from src.task.TacetTask import TacetTask
        from src.task.BaseCombatTask import CharRevivedException
        from cloud_daily_policy import PendingClaim
        from cloud_revive import recovery_navigation, world_heal_and_reenter
        if pending_claim is None:raise RuntimeError('Daily revival requires its account claim journal')
        material=task.get_task_by_class(TacetTask)
        native_material=material.farm_tacet
        def recover():
            with recovery_navigation(material):
                material.ensure_main(time_out=60)
                world_heal_and_reenter(material,reenter=False)
        def recheck():
            task.ensure_main(time_out=60)
            values=task.open_daily()
            task.back(after_sleep=1)
            return values
        def farm_tacet(daily=False,used_stamina=0,config=None):
            if not daily:return native_material(daily=daily,used_stamina=used_stamina,config=config)
            return run_tacet_daily(native_material,material=material,recheck=recheck,
                check_day=check_day,assert_clear=PendingClaim(pending_claim).assert_clear,
                recover=recover,revived_error=CharRevivedException,
                used_stamina=used_stamina,config=config)
        material.farm_tacet=farm_tacet
