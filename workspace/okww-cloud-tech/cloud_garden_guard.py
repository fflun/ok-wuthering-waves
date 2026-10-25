"""Weekly garden evidence; a diagnostic probe never enters the minigame."""
import json
from pathlib import Path
import re
import threading
import time


def parse_progress(texts):
    text=' '.join(str(getattr(box,'name',box)) for box in texts)
    text=text.replace(',','').replace('，','')
    pairs=re.findall(r'(?<!\d)(\d+)\s*[/／]\s*(6000)(?!\d)',text)
    values={(int(current),int(target)) for current,target in pairs}
    if len(values)!=1:raise RuntimeError('Garden progress is not positively readable: '+text)
    current,target=values.pop()
    if not 0<=current<=target:raise RuntimeError('Garden progress outside its verified range')
    return current,target


def page_value(current_texts,milestone_texts):
    current=[int(str(getattr(box,'name',box)).strip()) for box in current_texts
             if re.fullmatch(r'\d+',str(getattr(box,'name',box)).strip())]
    milestones={int(str(getattr(box,'name',box)).strip()) for box in milestone_texts
                if re.fullmatch(r'\d+',str(getattr(box,'name',box)).strip())}
    if len(current)!=1 or not set(range(1000,6001,1000)).issubset(milestones):
        raise RuntimeError('Garden current value or six reward milestones are unreadable')
    if not 0<=current[0]<=6000:raise RuntimeError('Garden current value outside weekly limit')
    return current[0],6000


def positioned_page_value(boxes):
    if not any(re.fullmatch('周度游历|周度遊歷',box.name.strip()) for box in boxes):
        raise RuntimeError('Weekly journey page title not verified')
    current=[box for box in boxes if .102<=box.x/1280<=.284 and .793<=box.y/720<=.956]
    markers=[box for box in boxes if .30<=box.x/1280<=.92 and .87<=box.y/720<=.96]
    return page_value(current,markers)


def result_progress(boxes):
    """The cap label must belong to the weekly-value row on a result page."""
    names=[box.name.strip() for box in boxes]
    caps=[box for box in boxes if re.fullmatch('已[达達](?:到)?上限',box.name.strip())]
    if not caps:return parse_progress(boxes)
    if any(re.search(r'[/／]\s*6[,，]?000',name) for name in names):
        raise RuntimeError('Garden result mixes a ratio and a cap label')
    if not any(re.fullmatch('挑[战戰](?:成功|失败|失敗)',name) for name in names):
        raise RuntimeError('Garden cap is outside a verified result page')
    if not any(re.fullmatch('返回主[页頁]',name) for name in names):
        raise RuntimeError('Garden result return control is missing')
    rows=[box for box in boxes if re.fullmatch('本周[游遊][历歷]值',box.name.strip())]
    if len(rows)!=1 or len(caps)!=1:raise RuntimeError('Garden weekly cap row is ambiguous')
    row,cap=rows[0],caps[0]
    if not (.38<=row.x/1280<=.55 and .50<=row.y/720<=.62
            and .68<=cap.x/1280<=.88 and abs(row.y-cap.y)<=16):
        raise RuntimeError('Garden cap does not belong to the weekly-value row')
    return 6000,6000


def claimed_tick_scores(frame):
    import cv2
    import hashlib
    asset=Path(__file__).resolve().parent/'assets/cloud/garden_claimed_tick.png'
    if hashlib.sha256(asset.read_bytes()).hexdigest()!='e3706786f86173b88ce3eed281d999346e9ab171cf10452b1ad0d53a4a55826e':
        raise RuntimeError('Garden claimed marker asset changed; review required')
    if frame.shape[:2]!=(720,1280):raise RuntimeError('Garden reward frame size changed')
    template=cv2.imread(str(asset),cv2.IMREAD_GRAYSCALE)
    scores=[]
    for x in (475,616,757,899,1041,1184):
        region=cv2.cvtColor(frame[622:656,x-18:x+18],cv2.COLOR_BGR2GRAY)
        scores.append(float(cv2.matchTemplate(region,template,cv2.TM_CCOEFF_NORMED).max()))
    return scores


def install(task,output,probe=False):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    native_run=task.run
    native_completed=task.is_weekly_garden_completed
    native_done=task.is_garden_done
    native_best=task.find_best_garden_feature
    native_find_one=task.find_one
    stop=threading.Event()
    last_action=[time.monotonic()]
    repeated=[None,0]
    def record(event,**data):
        with (output/'events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(at=time.time(),event=event,**data),ensure_ascii=False)+'\n')
    def snap(label):
        import cv2
        path=output/f'{time.time_ns()}-{label}.png'
        cv2.imwrite(str(path),task.frame)
        return path.name
    def dump(label):
        texts=[dict(text=box.name,x=box.x,y=box.y,width=box.width,height=box.height)
               for box in task.ocr(0,0,1,1)]
        (output/(label+'-ocr.json')).write_text(json.dumps(texts,ensure_ascii=False,indent=2),encoding='utf-8')
        record(label,image=snap(label))
        return texts
    def page_progress():
        from cloud_weekly_state import assert_expected_week
        assert_expected_week()
        def read():
            boxes=task.ocr(0,0,1,1)
            try:return positioned_page_value(boxes)
            except RuntimeError:
                dump('garden_unreadable_progress')
                raise
        first=read()
        task.sleep(.3)
        second=read()
        if first!=second:raise RuntimeError('Weekly garden progress changed between fresh reads')
        record('garden_progress',current=first[0],target=first[1],image=snap('progress'))
        return first
    def completed():
        current,target=page_progress()
        return current==target
    def done(texts):
        dump('garden_result')
        current,target=result_progress(task.ocr(0,0,1,1))
        record('garden_progress',current=current,target=target,source='verified result weekly-value row')
        return current==target
    def find_one(name,*args,**kwargs):
        if name=='a_garden_back':
            boxes=task.ocr(0,0,1,1)
            if any(re.fullmatch('已[达達](?:到)?上限',box.name.strip()) for box in boxes):
                result_progress(boxes)
                back=[box for box in boxes if re.fullmatch('返回主[页頁]',box.name.strip())]
                if len(back)!=1:raise RuntimeError('Garden return control is ambiguous')
                # Keep the original return action, using the text's center
                # instead of the old template's edge on this cap screen.
                return back[0]
        return native_find_one(name,*args,**kwargs)
    def best():
        from cloud_weekly_state import assert_expected_week
        assert_expected_week()
        target=native_best()
        if target:
            name=str(target.name)
            repeated[1]=repeated[1]+1 if repeated[0]==name else 1
            repeated[0]=name
            if repeated[1]>40:raise RuntimeError('Garden repeats the same action without leaving its state: '+name)
            last_action[0]=time.monotonic()
            record('garden_action',name=name,confidence=float(target.confidence))
        elif time.monotonic()-last_action[0]>75:
            dump('garden_stalled')
            raise RuntimeError('Garden has no recognized action for 75 seconds')
        return target
    def return_page():
        if not task.ocr(.24,.095,.42,.16,match=re.compile('周度游历|周度遊歷')):
            task.openF2Book('gray_book_quest')
            task.click(.343,.129,after_sleep=1)
        current,target=page_progress()
        if current!=target:raise RuntimeError('Native garden returned before the weekly target was reached')
    def verify_rewards():
        return_page()
        import os
        from cloud_autorun_state import day_key,week_key,write_json
        state_path=Path(__file__).resolve().parent.parent/'okww-cloud-session/background/garden-state.json'
        state=dict(status='PROGRESS_COMPLETE_REWARDS_PENDING',game_day=day_key(),game_week=week_key(),
                   run_id=os.environ.get('OKWW_RUN_ID'),current=6000,target=6000)
        write_json(state_path,state)
        # Inspect each positively located milestone. The game's reward dialog
        # must explicitly identify a claimed reward or a new reward grant.
        for index,x in enumerate((475,616,757,899,1041,1184),1):
            return_page()
            score=claimed_tick_scores(task.frame)[index-1]
            if score>=.90:
                task.sleep(.3)
                second=claimed_tick_scores(task.frame)[index-1]
                if second<.90:raise RuntimeError(f'Weekly reward {index} claimed marker changed')
                record('garden_reward_verified',milestone=index*1000,
                       source='two claimed checkmark reads on verified weekly page',
                       confidence=[score,second],image=snap('reward-verified'))
                continue
            task.click(x/1280,639/720,after_sleep=.8)
            boxes=task.ocr(0,0,1,1)
            texts=' '.join(box.name for box in boxes)
            dump(f'garden_reward_{index}')
            if '已领取' in texts or '已領取' in texts:
                source='explicit already claimed label'
            elif '获得奖励' in texts or '獲得獎勵' in texts:
                source='reward grant panel'
            else:
                claim_boxes=[box for box in boxes if re.fullmatch('领取|領取|领取奖励|領取獎勵',box.name.strip())]
                if len(claim_boxes)!=1 or not re.search('奖励|獎勵',texts):
                    raise RuntimeError(f'Weekly reward {index} has no positively verified claim state')
                task.click_box(claim_boxes[0],after_sleep=1)
                granted=task.wait_until(lambda:bool(task.ocr(0,0,1,1,match=re.compile('获得奖励|獲得獎勵|已领取|已領取'))),time_out=5)
                if not granted:raise RuntimeError(f'Weekly reward {index} grant not confirmed')
                source='claim followed by reward grant label'
            record('garden_reward_verified',milestone=index*1000,source=source,image=snap('reward-verified'))
            task.send_key('esc',after_sleep=.5)
        return_page()
        state.update(status='SUCCEEDED',verified_rewards=6,completed_at=time.time())
        write_json(state_path,state)
        record('garden_rewards_verified',verified_rewards=6,image=snap('all-rewards'))
    def observe():
        import cv2,os
        while not stop.wait(.2):
            try:
                frame=task.executor.nullable_frame()
                if frame is not None:
                    cv2.imwrite(str(output/'viewer-next.png'),frame,[cv2.IMWRITE_PNG_COMPRESSION,1])
                    os.replace(output/'viewer-next.png',output/'viewer.png')
            except Exception:pass
    def run():
        observer=threading.Thread(target=observe,daemon=True)
        observer.start()
        try:
            record('garden_probe_started' if probe else 'garden_started')
            if probe:
                from src.task.WWOneTimeTask import WWOneTimeTask
                WWOneTimeTask.run(task)
                task.ensure_main()
                task.open_garden_weekly_page()
                dump('garden_page')
                record('garden_probe_completed')
            else:
                task.is_weekly_garden_completed=completed
                task.is_garden_done=done
                task.find_best_garden_feature=best
                task.find_one=find_one
                # Resume the previously stopped cap screen through its own
                # return control; never choose the endless challenge button.
                boxes=task.ocr(0,0,1,1)
                if any(re.fullmatch('已[达達](?:到)?上限',box.name.strip()) for box in boxes):
                    result_progress(boxes)
                    task.sleep(.3)
                    fresh=task.ocr(0,0,1,1)
                    result_progress(fresh)
                    record('garden_max_confirmed',image=snap('max-confirmed'))
                    back=[box for box in fresh if re.fullmatch('返回主[页頁]',box.name.strip())]
                    if len(back)!=1:raise RuntimeError('Garden return control is ambiguous')
                    task.click_box(back[0],after_sleep=1)
                    if task.wait_feature('garden_start_game',settle_time=1,time_out=5):
                        task.back(after_sleep=1)
                native_run()
                verify_rewards()
        except BaseException as exc:
            record('batch_failed',error=str(exc),image=snap('failure'))
            raise
        finally:
            stop.set()
            observer.join(timeout=2)
            task.is_weekly_garden_completed=native_completed
            task.is_garden_done=native_done
            task.find_best_garden_feature=native_best
            task.find_one=native_find_one
            task.executor.interaction.release_all()
    task.run=run
