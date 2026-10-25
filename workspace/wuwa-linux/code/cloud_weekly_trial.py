"""Explicit weekly boss trial, preserving the native boss entry and rotation."""
import json
import re
from pathlib import Path


def weekly_dialog(task):
    text=''.join(b.name for b in task.ocr(.23,.3,.76,.53))
    text=re.sub(r'\s+','',text)
    return '领取奖励' in text and '消耗60点结晶波片' in text


def open_existing_weekly_reward(task):
    """Reconnect may change the left quest; use the fresh unclaimed interaction."""
    def present():
        labels = task.ocr(.65, .47, .80, .56, match=re.compile('^领取奖励$'))
        if len(labels) != 1:
            return False
        ok, index, count = task.in_team()
        return bool(ok and count == 3 and not task.has_health_bar())
    if not present():
        return False
    task.sleep(.3)
    task.next_frame()
    if not present():
        raise RuntimeError('Existing weekly reward interaction changed; no new combat')
    task.send_key('f', after_sleep=1)
    task.wait_until(lambda: weekly_dialog(task), time_out=5, raise_if_not_found=True)
    task.log_info('CLOUD_WEEKLY_RESUME existing unclaimed 60-point reward; no repeat combat')
    return True


def weekly_in_combat(task, original, *args, **kwargs):
    if task._cloud_weekly_victory or task.combat_end_condition():
        task._cloud_weekly_victory=True
        return task.reset_to_false(reason='verified weekly victory')
    return original(*args, **kwargs)


def exit_result(task):
    boxes=task.ocr(.25,.79,.45,.9,match=re.compile('^退出副本$'))
    if len(boxes)!=1:raise RuntimeError('Weekly result exit is not uniquely readable')
    task.click_box(boxes[0],after_sleep=2)
    task.wait_in_team_and_world(time_out=120)


def restart_stamina_warning(task):
    """Only the entry warning after a verified result; it does not claim rewards."""
    from cloud_daily_policy import verified_inventory
    def count():
        text = re.sub(r'\s+', '', ''.join(b.name for b in task.ocr(.24,.40,.78,.51)))
        match = re.fullmatch(r'领取奖励需要消耗60点结晶波片[，,]?当前拥有(\d+)点[，,]?是否继续[？?]?', text)
        return int(match[1]) if match and 0 <= int(match[1]) < 60 else None
    observed = count()
    if observed is None:
        return False
    task.sleep(.3); task.next_frame()
    if count() != observed:
        raise RuntimeError('Weekly restart stamina warning changed')
    current, reserve = verified_inventory(task)
    if current != observed:
        raise RuntimeError('Weekly restart warning inventory mismatch')
    boxes = task.ocr(.55,.59,.76,.67,match=re.compile('^确认$'))
    if len(boxes) != 1:
        raise RuntimeError('Weekly restart warning confirm is not unique')
    task.click_box(boxes[0], after_sleep=1)
    task.log_info('CLOUD_WEEKLY_RESTART stamina entry warning confirmed; no reward claim')
    return True


def resume_claimed_realm(task):
    """Reviewed entry-only failure after a verified claim can leave its old realm."""
    from cloud_autorun_state import week_key,write_json
    import os,hashlib,time,cv2
    state=Path(__file__).resolve().parent.parent/'okww-cloud-session/background'
    if os.environ.get('OKWW_WEEKLY_LEDGER') != str(state/'weekly-ledger.json'):
        return
    path=state/'weekly-entry-recovery-20261012.json'
    if not path.exists(): return
    request=json.loads(path.read_text(encoding='utf-8'))
    if request.get('status')!='READY':return
    records=json.loads((state/'weekly-ledger.json').read_text(encoding='utf-8'))
    claims=records.get(week_key(),{}).get('boss',{}).get('claims',[])
    if (request.get('game_week')!=week_key() or len(claims)!=request.get('completed_before')
            or not claims or claims[-1]['claim_id']!=request.get('last_claim_id')
            or request.get('reason')!='FAILED_AFTER_CLAIM_BEFORE_NEXT_COMBAT'):
        raise RuntimeError('Weekly entry recovery scope mismatch')
    if (state.parent/'claim-pending.json').exists():raise RuntimeError('Pending claim blocks realm recovery')
    task.next_frame()
    if weekly_dialog(task) or task.has_health_bar():raise RuntimeError('Unclaimed reward or active enemy blocks claimed realm exit')
    ok,index,count=task.in_team()
    if not ok or count!=3:raise RuntimeError('Team unavailable for reviewed weekly exit')
    task.ensure_main(time_out=30)
    task.next_frame()
    if task.in_realm() or not task.in_world():raise RuntimeError('Weekly reviewed exit did not reach world')
    image=Path(request['output'])/'recovered-world.png'
    if not cv2.imwrite(str(image),task.frame):raise RuntimeError('Weekly recovery image could not be saved')
    request.update(status='DONE',verified_at=time.time(),image=str(image),sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    write_json(path,request)
    task.log_info('CLOUD_WEEKLY_RESTART previous material claim retained; returned from claimed realm')


def restart_result(task):
    """Restart only from a successful material result with a unique control."""
    if not task.ocr(.25,.24,.75,.37,match=re.compile('挑战成功|挑戰成功')):
        raise RuntimeError('Weekly successful result not verified before restart')
    boxes=task.ocr(.50,.79,.75,.9,match=re.compile('^(重新挑战|重新挑戰|继续挑战|继续开始|再次挑战)$'))
    if len(boxes)!=1:raise RuntimeError('Weekly result restart is not uniquely readable')
    task.click_box(boxes[0],after_sleep=2)
    task.wait_until(lambda: restart_stamina_warning(task), time_out=2, raise_if_not_found=False)
    task.wait_in_team_and_world(time_out=120)


def material_combat(task, original, restarted=False):
    """Keep native entry/rotation; skip echo search and redundant teleport."""
    pick_echo,walk_find_echo=task.pick_echo,task.walk_find_echo
    teleport=task.config['Teleport to Boss']
    just_entered=getattr(task,'_just_entered_boss_realm',False)
    task.pick_echo=lambda *args,**kwargs:False
    task.walk_find_echo=lambda *args,**kwargs:False
    if restarted:
        task.config['Teleport to Boss']='No'
        task._just_entered_boss_realm=True
    try:
        return original()
    finally:
        task.pick_echo,task.walk_find_echo=pick_echo,walk_find_echo
        task.config['Teleport to Boss']=teleport
        task._just_entered_boss_realm=just_entered


def claim_weekly(task, output, number):
    from cloud_daily_policy import PendingClaim, verified_inventory, refill, text_in
    from cloud_weekly_state import assert_expected_week,record_live_boss_claim
    assert_expected_week()
    journal=PendingClaim(Path(__file__).resolve().parent.parent/'okww-cloud-session/claim-pending.json')
    journal.assert_clear()
    if not weekly_dialog(task):raise RuntimeError('Weekly 60-point reward prompt not verified')
    current,reserve=verified_inventory(task)
    journal.begin(current,reserve,60)
    if current<60:
        refill(task,60,inventory=(current,reserve))
        current,reserve=verified_inventory(task)
    if not weekly_dialog(task):raise RuntimeError('Weekly prompt changed before confirm')
    boxes=task.ocr(.55,.59,.76,.67,match=re.compile('^确认$'))
    if len(boxes)!=1:raise RuntimeError('Weekly confirmation not uniquely readable')
    assert_expected_week()
    task.click_box(boxes[0],after_sleep=1)
    def verify():
        if weekly_dialog(task):return False
        try:
            after,after_reserve=verified_inventory(task)
            if current-60<=after<=current-59 and reserve==after_reserve:return True
        except (RuntimeError,ValueError):pass
        text=text_in(task,(.2,.72,.85,.96))
        remaining=re.findall(r'剩[余餘]\s*(\d+)',text)
        return bool(len(remaining)==1 and current-60<=int(remaining[0])<=current-59
                    and re.search('退出|离开',text) and re.search('重新挑战|再次挑战',text))
    task.wait_until(verify,time_out=10,raise_if_not_found=True)
    import cv2
    image=output/f'weekly-claim-{number}.png'
    if not cv2.imwrite(str(image),task.frame):raise RuntimeError('Weekly claim image could not be saved')
    record_live_boss_claim(image,number)
    journal.complete()
    task.info['Weekly Verified Claims']=number
    task.log_info(f'CLOUD_WEEKLY_VERIFIED round={number} cost=60')


def install_probe(task, output, rounds=0):
    if rounds not in (0,1,2,3):raise ValueError('Weekly run limited to at most three claims')
    original = task.do_run
    original_end=task.combat_end_condition
    original_in_combat=task.in_combat
    original_wait = task.wait_feature
    original_team=task.click_team_challenge
    def click_team_challenge():
        text=''.join(b.name for b in task.ocr(.28,.4,.73,.5))
        if '结晶波片不足' in text and '继续进入' in text:
            boxes=task.ocr(.55,.59,.76,.67,match=re.compile('^确认$'))
            if len(boxes)!=1:raise RuntimeError('Stamina warning confirm not uniquely readable')
            task.click_box(boxes[0],after_sleep=1)
        return original_team()
    task.click_team_challenge=click_team_challenge
    def wait_feature(names, *args, **kwargs):
        if names == ['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close']:
            text=''.join(b.name for b in task.ocr(.25,.4,.75,.54))
            if '提前到达' in text and '是否确认前往' in text:
                import re
                boxes=task.ocr(.55,.59,.76,.67,match=re.compile('^确认$'))
                if len(boxes)!=1:
                    raise RuntimeError('Weekly story-warning confirmation is unreadable')
                task.click_box(boxes[0],after_sleep=1)
        return original_wait(names,*args,**kwargs)
    task.wait_feature=wait_feature
    original_has_claim=task.has_claim_stamina
    task.has_claim_stamina=lambda: weekly_dialog(task) or original_has_claim()
    settings={'Teleport to Boss':'Weekly Challenge','Which Weekly Boss to Teleport':1,
              'Boss Level':'90','Boss':'Other','Repeat Farm Count':1,
              'Combat Wait Time':0,'Echo Pickup Method':'Walk','Use Liberation':True,
              'Switch to Healer before and after Combat':True,'Exit After Task':False}
    backup={key:task.config.get(key) for key in settings}
    def run_impl():
        import cv2
        try:
            task.config.update(settings)
            from src.task.WWOneTimeTask import WWOneTimeTask
            WWOneTimeTask.run(task)
            task.use_liberation=True
            task._cloud_weekly_trial=True
            task.teleport_timeout=120
            # Material farming must not end when the echo detector finds a
            # shape during combat. Require the game's completed objective.
            import re
            task.combat_end_condition=lambda: bool(task.ocr(.01,.21,.25,.31,
                match=re.compile('领取奖励|領取獎勵')))
            task._cloud_weekly_victory=False
            def in_combat(*args, **kwargs):
                return weekly_in_combat(task, original_in_combat, *args, **kwargs)
            task.in_combat=in_combat
            output.mkdir(parents=True,exist_ok=True)
            from cloud_weekly_probe_endpoint import enabled as replay_enabled,prepare_entry,finish_probe
            replay_mode=not rounds and replay_enabled()
            if replay_mode:prepare_entry(task,output)
            if task.ocr(.25,.79,.45,.9,match=re.compile('^退出副本$')):
                exit_result(task)
            resume_claimed_realm(task)
            import os
            ledger_path=os.environ.get('OKWW_WEEKLY_LEDGER')
            prior_claims=(json.loads(Path(ledger_path).read_text(encoding='utf-8')).get(
                os.environ.get('OKWW_WEEKLY_WEEK'),{}).get('boss',{}).get('claims',[]) if ledger_path else [])
            allow_existing_reward=bool(ledger_path and not prior_claims)
            restarted=False
            for number in range(1,(rounds or 1)+1):
                task._cloud_weekly_victory=False
                if not weekly_dialog(task) and not (allow_existing_reward and open_existing_weekly_reward(task)):
                    from cloud_revive import recover_before_entry
                    if recover_before_entry(task):restarted=True
                    from cloud_weekly_recovery import recovery
                    if task.combat_end_condition():
                        task.load_chars()
                    else:
                        with recovery(task):
                            material_combat(task,original,restarted=restarted)
                    if not task.wait_until(task.combat_end_condition,time_out=8):
                        raise RuntimeError('Weekly victory objective not confirmed; no reward navigation')
                    task._cloud_weekly_victory=True
                    task.reset_to_false(reason='verified weekly victory before reward walking')
                    task.walk_to_treasure()
                    if not replay_mode:task.pick_f(handle_claim=False)
                    task.sleep(1)
                if replay_mode:
                    finish_probe(task,output)
                    raise RuntimeError('WEEKLY_PROBE_ONLY: quota endpoint and world exit verified; no reward claimed')
                cv2.imwrite(str(output/'weekly-reward-probe.png'),task.frame)
                if not rounds:
                    boxes=task.ocr(0,0,1,1)
                    (output/'weekly-reward-probe.json').write_text(json.dumps([
                        {'text':b.name,'x':b.x,'y':b.y,'width':b.width,'height':b.height}
                        for b in boxes],ensure_ascii=False,indent=2),encoding='utf-8')
                    raise RuntimeError('WEEKLY_PROBE_ONLY: reward screen captured; no reward claimed')
                claim_weekly(task,output,number)
                allow_existing_reward=False
                task.sleep(2)
                if number<rounds:
                    restart_result(task)
                    restarted=True
                else:
                    exit_result(task)
            if rounds and task.info.get('Weekly Verified Claims')!=rounds:
                raise RuntimeError('Weekly claim count incomplete')
        finally:
            task.config.update(backup)
            task.wait_feature=original_wait
            task.click_team_challenge=original_team
            task.has_claim_stamina=original_has_claim
            task.combat_end_condition=original_end
            task.in_combat=original_in_combat
            task._cloud_weekly_trial=False
            task._cloud_weekly_victory=False
    def run():
        from cloud_revive import revive_policy
        entry={key:settings[key] for key in ('Teleport to Boss','Which Weekly Boss to Teleport','Boss Level')}
        with revive_policy(task,entry):return run_impl()
    task.run=run
