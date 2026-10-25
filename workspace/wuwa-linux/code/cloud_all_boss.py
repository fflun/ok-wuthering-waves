"""One explicitly named native 4C boss batch; rotations are upstream methods."""
import json,re,time,threading,os
from pathlib import Path
from cloud_autorun_state import day_key,write_json
from cloud_echo_progress import EchoProgress


class BossUnavailable(RuntimeError):pass


def positive_victory(*,seen,team,enemies,active,recovery,reward):
    return bool(seen and team and reward and not (enemies or active or recovery))

def normalized_name(name):return re.sub(r'\s+','',name).replace('・','·')

def active_instance_objective(text):return bool(re.search('击败敌人|擊敗敵人',text))

def named_active_battle(task,target):
    """Fresh target name plus full team and objective or enemy HP; never victory."""
    task.next_frame()
    title=''.join(b.name for b in task.ocr(.30,0,.72,.08))
    team,_,count=task.in_team()
    named=any(normalized_name(n) in normalized_name(title)
              for n in [target['name']]+target.get('aliases',[]))
    if not (team and count==3 and named):return False
    if task.ocr(.18,.14,.5,.25,match=re.compile('选择复苏物品|選擇復甦物品')):return False
    objective=''.join(b.name for b in task.ocr(.01,.20,.34,.32))
    return bool(active_instance_objective(objective) or task.check_health_bar())

def protect_named_instance(task,target):
    """Enable existing protection only from fresh, named active battle evidence."""
    if named_active_battle(task,target):
        task._cloud_weekly_trial=True
        return True
    return False


def prepare_named_entry(task,target,native):
    result=native()
    if protect_named_instance(task,target):
        task.log_info('CLOUD_BOSS named active entry; objective protection before native wait')
    return result

def retain_named_instance(task,target,native_navigation,*args,**kwargs):
    """Keep native approach logic in an already verified challenge scene."""
    if protect_named_instance(task,target):
        task.log_info('CLOUD_BOSS named active instance; retain native approach without world map')
        return
    return native_navigation(*args,**kwargs)

def finish_verified_entry(task):
    """A recovery entry was consumed by this fight, not the following round."""
    task._just_entered_boss_realm=False

def manage_named_interactions(task,completed,pending,native):
    # Let the common native realm restart handle a finished challenge before
    # Nameless Explorer's old world-navigation special case runs again.
    if task.config.get('Boss')=='Nameless Explorer' and completed>0 and not pending and task._in_realm:
        team,_,count=task.in_team()
        objective=''.join(b.name for b in task.ocr(.01,.20,.34,.32))
        if team and count==3 and not task.check_health_bar() and re.search('领取奖励|領取獎勵',objective):
            task.log_info('CLOUD_BOSS verified prior pickup and cleared realm; use native common restart')
            return
    return native()

def pickup_has_enemies(task):
    return bool(task.check_health_bar() or active_instance_objective(
        ''.join(b.name for b in task.ocr(.01,.20,.34,.32))))

def wait_account_ready(task,read_identity,verify_identity,snapshot,*,timeout=60,clock=time.monotonic):
    """Loading surfaces do not authorize game input or skip account binding."""
    capture=task.executor.method
    previous_block=capture.block_input;capture.block_input=True
    deadline=clock()+timeout
    while clock()<deadline:
        try:identity=read_identity(task)
        except RuntimeError as exc:
            if str(exc)!='Game account identifier unreadable; no nest action':raise
            snapshot('identity-wait')
            task.log_info('CLOUD_BOSS loading handoff; inputs blocked while waiting for account')
            task.sleep(min(2,max(0,deadline-clock())))
            continue
        verify_identity(identity)  # wrong accounts stop immediately
        capture.block_input=previous_block
        return identity
    raise RuntimeError('Boss browser handoff account unverified after60 seconds; no input sent')


def install(task,target,output,progress_path,run_id,day):
    import cv2
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    native_run=task.run
    running=[False]
    def record(event,**data):
        with (output/'events.jsonl').open('a',encoding='utf8') as f:
            f.write(json.dumps(dict(at=time.time(),event=event,target=target['name'],**data),ensure_ascii=False)+'\n')
    def snap(label):
        path=output/f'{time.time_ns()}-{label}.png';cv2.imwrite(str(path),task.frame);return str(path)
    def run():
        if running[0]:raise RuntimeError('Native error attempted recursive batch restart; checkpoint recovery required')
        running[0]=True
        from cloud_accounts import verify_account_identity
        from cloud_nest_current import read_account
        from cloud_revive import revive_policy
        from cloud_weekly_recovery import recovery
        from src.task.FarmEchoTask import FarmEchoTask
        state=Path(__file__).resolve().parent.parent/'okww-cloud-session/background'
        registry=json.loads((state/'accounts/registry.json').read_text(encoding='utf8'))
        uid=wait_account_ready(task,read_account,lambda value:verify_account_identity(registry,'a',value),snap)
        progress=EchoProgress(progress_path,uid,day,target['key']);progress.assert_day()
        if progress.completed==20:return
        stop=threading.Event()
        def watch():
            while not stop.wait(.2):
                try:
                    frame=task.executor.nullable_frame()
                    if frame is not None:
                        cv2.imwrite(str(output/'viewer-next.png'),frame,[cv2.IMWRITE_PNG_COMPRESSION,1])
                        os.replace(output/'viewer-next.png',output/'viewer.png')
                except Exception:pass
        threading.Thread(target=watch,daemon=True).start()
        names=('combat_once','combat_end_condition','in_combat','incr_drop','use_stamina',
               'click_on_book_target','wait_feature','click_team_challenge','on_combat_check',
               'should_reteleport_after_farm_exception','teleport_to_configured_boss_and_prepare',
               'teleport_to_nearest_boss','manage_boss_interactions')
        original={name:getattr(task,name) for name in names}
        weekly=target['feature']=='zhange'
        settings={'Teleport to Boss':'Weekly Challenge' if weekly else 'Boss Challenge',
                  'Boss Level':'80','Boss':target.get('profile','Other'),
                  'Repeat Farm Count':20-progress.completed,'Echo Pickup Method':'Walk',
                  'Exit After Task':False}
        saved={name:task.config.get(name) for name in settings}
        echo_only_before=getattr(task,'_cloud_echo_only',None)
        task._cloud_echo_only=True
        seen=[False];gate=[None,0,None];last=[0,False]
        retain=[not progress.pending and named_active_battle(task,target)]
        def teleport():
            if retain[0]:
                retain[0]=False
                task._in_realm=True;task.treat_as_not_in_realm=False
                task._just_entered_boss_realm=True;task.init_parameters()
                protect_named_instance(task,target)
                record('active_battle_retained',image=snap('active-battle-retained'))
                return
            return prepare_named_entry(task,target,original['teleport_to_configured_boss_and_prepare'])
        def victory():
            now=time.monotonic()
            if now-last[0]<.25:return last[1]
            frame=task.frame
            ok,index,count=task.in_team()
            enemies=bool(task.check_health_bar())
            seen[0]=seen[0] or enemies
            objective=''.join(b.name for b in task.ocr(.01,.20,.34,.32))
            active=active_instance_objective(objective)
            recovery_ui=bool(task.ocr(.18,.14,.5,.25,match=re.compile('选择复苏物品|選擇復甦物品')))
            reward=bool(re.search('领取奖励|領取獎勵',objective) or task.find_treasure_icon()
                        or task.find_f_with_text(target_text=task.absorb_echo_text()))
            positive=positive_victory(seen=seen[0],team=ok and count==3,enemies=enemies,
                                     active=active,recovery=recovery_ui,reward=reward)
            if not positive:gate[:]=[None,0,None]
            elif frame is not gate[2]:
                gate[0]=gate[0] if gate[0] is not None else now
                gate[1]+=1;gate[2]=frame
            result=bool(positive and gate[1]>=3 and now-gate[0]>=1)
            last[:]=[now,result];return result
        def in_combat(*args,**kwargs):
            if progress.pending:
                if pickup_has_enemies(task):raise RuntimeError('Verified pickup scene regained enemy evidence; stop')
                return task.reset_to_false(reason='persisted verified victory; native echo pickup phase')
            if seen[0] and victory():return task.reset_to_false(reason='verified named boss victory')
            result=original['in_combat'](*args,**kwargs)
            if result:seen[0]=True
            return result
        def combat(*args,**kwargs):
            progress.assert_day()
            if progress.pending or progress.completed>=20:raise RuntimeError('Unfinished pickup or quota reached')
            seen[0]=False;gate[:]=[None,0,None];last[:]=[0,False]
            # Normal Boss Challenge now also opens a challenge instance.
            # Reuse the proven objective/cinematic protection in that scene,
            # rather than ending native output when a nearly empty HP bar
            # or temporary lock loss becomes visually undetectable.
            task._cloud_weekly_trial=weekly or named_active_battle(task,target)
            record('combat_started',round=progress.completed+1,image=snap('combat-start'))
            task.combat_once=original['combat_once']
            try:
                with recovery(task,active_check=lambda: protect_named_instance(task,target)):
                    kwargs.setdefault('target',True)
                    result=task.combat_once(*args,**kwargs)
            finally:task.combat_once=combat
            if not task.wait_until(victory,time_out=8):raise RuntimeError('Named boss victory not positively verified')
            # Reentry during death recovery sets the native first-entry flag.
            # This fight has already consumed it; leaving it set would skip
            # the next round's native restart and fight the old cleared scene.
            finish_verified_entry(task)
            image=snap('verified-victory');progress.victory(run_id,image)
            record('combat_returned',round=progress.pending['round'],image=image)
            return result
        def drop(dropped):
            if not progress.pending:raise RuntimeError('Pickup result without a verified victory')
            progress.pickup_finished(dropped,snap('pickup-search-result'))
            record('round_checkpoint',completed=progress.completed,absorbed=bool(dropped))
            return original['incr_drop'](dropped)
        def forbidden(*args,**kwargs):raise RuntimeError('Echo-only batch forbids all stamina rewards')
        def select(*args,**kwargs):
            # Match the named card itself. Never trust a stale serial number.
            category={'qiangdi':'讨伐强敌','zhange':'战歌重奏'}[target['feature']]
            for attempt in range(2):
                category_boxes=task.ocr(.12,.12,.35,.88,match=re.compile('^'+category+'$'))
                if len(category_boxes)!=1:raise RuntimeError('Boss category label not uniquely verified')
                task.click_box(category_boxes[0],after_sleep=2);task.next_frame()
                if any('筛选查看' in b.name for b in task.ocr(.36,.12,.70,.24)):break
            else:raise RuntimeError('Boss category contents not verified')
            for page,y in enumerate([.191+i*.025 for i in range(28)]+[.88,.88]):
                task.click(.974,min(y,.88),after_sleep=.5)
                progress.assert_day();task.next_frame()
                boxes=task.ocr(.30,.12,.91,.87)
                accepted={normalized_name(n) for n in [target['name']]+target.get('aliases',[])}
                exact=[b for b in boxes if normalized_name(b.name) in accepted]
                if len(exact)>1:raise RuntimeError('Ambiguous named boss card')
                if exact:
                    title=exact[0]
                    if title.y<120 or title.y>555:continue
                    card=task.ocr(.30,title.y/task.height,.97,min((title.y+105)/task.height,.88))
                    if any(re.search('未解锁|未開放|尚未解锁|尚未开放',b.name) for b in card):
                        record('boss_unavailable',image=snap('locked-card'));raise BossUnavailable(target['name'])
                    buttons=task.find_feature('boss_proceed',box=task.box_of_screen(.90,title.y/task.height,.97,min((title.y+110)/task.height,.88)),threshold=.70)
                    if len(buttons)!=1:raise RuntimeError('Named boss entry button not uniquely verified')
                    record('named_entry_verified',page=page,image=snap('named-entry'))
                    task.click(buttons[0],after_sleep=1)
                    feature=task.wait_feature(['fast_travel_custom','gray_teleport','remove_custom','team_close'],time_out=10,settle_time=.5,raise_if_not_found=True)
                    return feature.name=='team_close'
            raise RuntimeError('Named boss navigation exceeded bounded catalog search')
        def wait_feature(names,*args,**kwargs):
            if names==['fast_travel_custom','gray_teleport','remove_custom','team_close']:
                text=''.join(b.name for b in task.ocr(.25,.4,.75,.54))
                if '提前到达' in text and '是否确认前往' in text:
                    boxes=task.ocr(.55,.59,.76,.67,match=re.compile('^确认$'))
                    if len(boxes)!=1:raise RuntimeError('Entry warning unreadable')
                    task.click_box(boxes[0],after_sleep=1)
            return original['wait_feature'](names,*args,**kwargs)
        def team():
            text=''.join(b.name for b in task.ocr(.28,.4,.73,.5))
            if '结晶波片不足' in text and '继续进入' in text:
                boxes=task.ocr(.55,.59,.76,.67,match=re.compile('^确认$'))
                if len(boxes)!=1:raise RuntimeError('Entry stamina warning unreadable')
                task.click_box(boxes[0],after_sleep=1)
            return original['click_team_challenge']()
        task.config.update(settings)
        task.combat_once=combat;task.combat_end_condition=victory;task.in_combat=in_combat
        task.incr_drop=drop;task.use_stamina=forbidden;task.click_on_book_target=select
        task.wait_feature=wait_feature;task.click_team_challenge=team
        task.on_combat_check=lambda:True
        task.should_reteleport_after_farm_exception=lambda:False
        task.teleport_to_configured_boss_and_prepare=teleport
        task.teleport_to_nearest_boss=lambda *a,**k:retain_named_instance(
            task,target,original['teleport_to_nearest_boss'],*a,**k)
        task.manage_boss_interactions=lambda:manage_named_interactions(
            task,progress.completed,progress.pending,original['manage_boss_interactions'])
        task._cloud_weekly_trial=weekly or retain[0]
        try:
            record('batch_started',resumed_completed=progress.completed,settings=settings)
            clearance_path=Path(progress_path).parent.parent/'resume-clearance.json'
            if clearance_path.exists():
                permit=json.loads(clearance_path.read_text(encoding='utf8'))
                if permit.get('status')=='READY' and permit.get('target')==target['key']:
                    if (permit.get('game_day')!=day or permit.get('completed_before')!=progress.completed
                            or progress.pending or time.time()>permit['expires_at']):
                        raise RuntimeError('Clearance recovery permit is stale or conflicts with progress')
                    # Prior same-target combat is evidenced in the failed run;
                    # only fresh stable positive victory can create a checkpoint.
                    seen[0]=True
                    if not task.wait_until(victory,time_out=8):
                        raise RuntimeError('Fresh same-target cleared scene not positively verified')
                    image=snap('resumed-verified-victory');progress.victory(run_id,image)
                    permit.update(status='USED',image=image,used_at=time.time());write_json(clearance_path,permit)
                    record('cleared_round_restored',round=progress.pending['round'],image=image)
            if progress.pending:
                # Search the saved victory before any navigation or new fight.
                if not task.in_team()[0] or task.check_health_bar():raise RuntimeError('Pending pickup scene not safe')
                task._in_realm=task.in_realm()
                task.manage_boss_parameters();task.init_parameters()
                task.load_chars();drop(task.pick_echo() or task.walk_find_echo())
                task.config['Repeat Farm Count']=20-progress.completed
            from cloud_boss_food import prepare_reentry
            def leave_for_food():
                from cloud_boss_food import leave_instance_for_food
                leave_instance_for_food(task)
                retain[0]=False
            if prepare_reentry(task,output,uid,target['key'],state,
                    state/'boss-reentry-food-20261008.json',progress.completed,leave_for_food):
                retain[0]=False
                record('reentry_food_verified',completed=progress.completed)
            policy_path=state/'boss-food-policy-20261008.json'
            if policy_path.exists():
                policy=json.loads(policy_path.read_text(encoding='utf8'))
                if policy.get('game_day')!=day or policy.get('account')!='a' or policy.get('item')!='糖醋里脊':
                    raise RuntimeError('Boss food policy scope mismatch')
                if target['key']!=policy['first_target']:
                    from cloud_boss_food import prepare_transition
                    prepare_transition(task,output,uid,target['key'],state,completed=progress.completed,
                        renew_after_seconds=policy.get('renew_after_seconds',1500))
            with revive_policy(task,settings):
                healing_path=state/'boss-heal-recovery-20261008.json'
                if healing_path.exists():
                    heal=json.loads(healing_path.read_text(encoding='utf8'))
                    if heal.get('target')==target['key'] and heal.get('status')=='READY':
                        if heal.get('game_day')!=day or heal.get('completed_before')!=progress.completed or progress.pending:
                            raise RuntimeError('Death healing preflight conflicts with checkpoint')
                        from cloud_revive import recovery_navigation,world_heal_and_reenter
                        with recovery_navigation(task):world_heal_and_reenter(task,reenter=False)
                        retain[0]=False
                        heal.update(status='DONE',verified_at=time.time());write_json(healing_path,heal)
                        record('death_healing_preflight_verified',completed=progress.completed,image=snap('healed-before-entry'))
                native_run()
            if progress.completed!=20 or progress.pending:raise RuntimeError('Native task stopped before20 verified victories')
            record('batch_succeeded',completed=20,absorbed=sum(r['absorbed'] for r in progress.record['rounds']))
            write_json(output/'batch-result.json',dict(status='SUCCEEDED',run_id=run_id,target=target['key'],game_day=day,completed=20,progress=str(progress.path)))
        except BossUnavailable:
            write_json(output/'batch-result.json',dict(status='UNAVAILABLE',run_id=run_id,target=target['key'],game_day=day,image=snap('unavailable')))
            task.ensure_main(time_out=30)
        except BaseException as exc:
            try:image=snap('failure')
            except Exception:image=None
            record('batch_failed',error=str(exc),image=image);raise
        finally:
            stop.set();task.config.update(saved);task._cloud_weekly_trial=False;running[0]=False
            if echo_only_before is None:task.__dict__.pop('_cloud_echo_only',None)
            else:task._cloud_echo_only=echo_only_before
            for name,value in original.items():setattr(task,name,value)
            task.executor.interaction.release_all()
    task.run=run
