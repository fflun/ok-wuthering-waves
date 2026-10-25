# SPDX-License-Identifier: AGPL-3.0-only
# Experimental Linux integration snapshot, modified 2026-10-25 by fflun.
"""Explicit child process for the two previously exercised echo-only flows.
Imported helpers do not launch a game. The parent holds the shared runner lock.
"""
import json,os,re,threading,time
from pathlib import Path

def ensure_nest_catalog(task):
    """Wait for real rows; one positively identified tab correction at most."""
    from cloud_nest_entry import count
    def ready():
        task.next_frame()
        boxes=task.ocr(.35,.13,1,.96)
        return (any(count(b.name) for b in boxes)
                and any(re.search(r'残[象像]聚落$',b.name.strip()) for b in boxes))
    def wait():
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if ready():return True
            task.sleep(.25)
        return False
    if wait():return
    def tab():
        task.next_frame()
        boxes=task.ocr(0,0,1,.96)
        names=[b for b in boxes if b.name.strip()=='残象聚落'
               and 100<=b.x<=440 and 100<=b.y<=650]
        return names[0] if len(names)==1 and any(b.name.strip()=='素材获取' for b in boxes) else None
    first=tab()
    task.sleep(.25)
    second=tab()
    if (first is None or second is None or abs(first.x-second.x)>8 or abs(first.y-second.y)>8):
        raise RuntimeError('Nest catalog tab not positively identified; stopped')
    task.log_info('CLOUD_NEST_CATALOG correcting positively identified tab once')
    task.click(second,after_sleep=.5)
    if not wait():raise RuntimeError('Nest catalog rows absent after one verified tab correction')

def boss_child(output):
    OUT=Path(output)
    import cv2,re
    from src.task.FarmEchoTask import FarmEchoTask
    original_run=FarmEchoTask.run
    def run_impl(self, recovered=False):
        def record(event,**data):
            with (OUT/'events.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps(dict(at=time.time(),event=event,**data),ensure_ascii=False)+'\n')
        def snap(label):
            name=f'{time.time_ns()}-{label}.png'
            cv2.imwrite(str(OUT/name),self.frame)
            return name
        stop=threading.Event()
        from cloud_autorun_state import day_key
        from cloud_echo_progress import EchoProgress,resume_scene
        day=os.environ.get('OKWW_FULL_DAY',day_key())
        progress_path=Path(__file__).resolve().parent.parent/'okww-cloud-session/background'/f'boss-echo-progress-{day}.json'
        pending_before=json.loads(progress_path.read_text(encoding='utf-8')).get('pending') if progress_path.exists() else None
        scene=resume_scene(self,pending=bool(pending_before))
        if not recovered and scene is None:
            self.ensure_main(time_out=60)
        elif not self.in_team()[0]:
            raise RuntimeError('Recovered boss no longer has its playable team HUD')
        accounts=re.findall(r'(?<!\d)\d{9}(?!\d)', ''.join(b.name for b in self.ocr(.80,.96,1,1)))
        if len(accounts)!=1:raise RuntimeError('Boss account is unreadable; cannot resume progress')
        progress=EchoProgress(progress_path,accounts[0],day)
        progress.assert_day()
        def observe():
            while not stop.wait(.15):
                try:
                    frame=self.executor.nullable_frame()
                    if frame is not None:
                        cv2.imwrite(str(OUT/'viewer-next.png'),frame,[cv2.IMWRITE_PNG_COMPRESSION,1])
                        os.replace(OUT/'viewer-next.png',OUT/'viewer.png')
                except Exception:pass
        threading.Thread(target=observe,daemon=True).start()
        settings={'Teleport to Boss':'Weekly Challenge','Which Weekly Boss to Teleport':1,
                  'Boss Level':'80','Boss':'Other','Repeat Farm Count':20-progress.completed,
                  'Echo Pickup Method':'Walk','Exit After Task':False}
        saved={k:self.config.get(k) for k in settings}
        originals={k:getattr(self,k) for k in ('combat_once','pick_echo','incr_drop','use_stamina','wait_feature','click_team_challenge','should_reteleport_after_farm_exception','in_combat','combat_end_condition','teleport_to_configured_boss_and_prepare')}
        retain_current=[recovered or scene=='active']
        def teleport():
            if retain_current[0]:
                retain_current[0]=False
                self._in_realm=True;self.treat_as_not_in_realm=False
                self._just_entered_boss_realm=True
                self.init_parameters()
                self.log_info('CLOUD_REVIVE retain recovered boss; no initial re-teleport')
                return
            return originals['teleport_to_configured_boss_and_prepare']()
        battles=[progress.completed];pickups=[0]
        def combat(*args,**kwargs):
            if battles[0]>=20:raise RuntimeError('Twenty-combat limit reached')
            progress.assert_day()
            battles[0]+=1
            title=''.join(b.name for b in self.ocr(.30,0,.72,.075))
            if not ('80' in title and ('天演溯心' in title or '衍律化形' in title)):
                raise RuntimeError('Expected level 80 boss title not verified: '+title)
            record('combat_started',round=battles[0],boss_title=title,image=snap('combat-start'))
            from cloud_weekly_recovery import recovery
            self.combat_once=originals['combat_once']
            try:
                with recovery(self):
                    # Native acquisition, as exercised in the successful revive
                    # trial. No replacement of character output or combat loop.
                    kwargs.setdefault('target',True)
                    result=self.combat_once(*args,**kwargs)
            finally:
                self.combat_once=combat
            if not self.combat_end_condition():
                raise RuntimeError('Boss victory objective not verified')
            record('combat_returned',round=battles[0],image=snap('combat-return'))
            progress.victory(os.environ['OKWW_FULL_RUN_ID'],str(OUT/snap('verified-victory')))
            return result
        def pick_echo(*args,**kwargs):
            result=originals['pick_echo'](*args,**kwargs)
            if result:
                pickups[0]+=1
                record('echo_absorbed',round=battles[0],image=snap('absorbed'))
            return result
        def incr_drop(dropped):
            record('native_drop_result',round=battles[0],dropped=bool(dropped),image=snap('pickup-result'))
            if progress.pending:
                battles[0]=progress.pending['round']
                progress.pickup_finished(dropped,str(OUT/snap('verified-pickup-search')))
                record('round_checkpoint',completed=progress.completed,dropped=bool(dropped))
            return originals['incr_drop'](dropped)
        def forbidden(*args,**kwargs):raise RuntimeError('Echo-only run forbids stamina reward claims')
        # Existing verified entry dialogs; neither is a purchase/claim dialog.
        def wait_feature(names,*args,**kwargs):
            if names==['fast_travel_custom','gray_teleport','remove_custom','team_close']:
                text=''.join(b.name for b in self.ocr(.25,.4,.75,.54))
                if '提前到达' in text and '是否确认前往' in text:
                    boxes=self.ocr(.55,.59,.76,.67,match=re.compile('^确认$'))
                    if len(boxes)!=1:raise RuntimeError('Entry warning unreadable')
                    self.click_box(boxes[0],after_sleep=1)
            return originals['wait_feature'](names,*args,**kwargs)
        def team():
            text=''.join(b.name for b in self.ocr(.28,.4,.73,.5))
            if '结晶波片不足' in text and '继续进入' in text:
                boxes=self.ocr(.55,.59,.76,.67,match=re.compile('^确认$'))
                if len(boxes)!=1:raise RuntimeError('Entry stamina warning unreadable')
                self.click_box(boxes[0],after_sleep=1)
            return originals['click_team_challenge']()
        self.combat_once=combat;self.pick_echo=pick_echo;self.incr_drop=incr_drop
        self.use_stamina=forbidden;self.wait_feature=wait_feature;self.click_team_challenge=team
        self.should_reteleport_after_farm_exception=lambda:False
        self.teleport_to_configured_boss_and_prepare=teleport
        self._cloud_weekly_trial=True
        self.combat_end_condition=lambda:bool(self.ocr(.01,.21,.25,.31,match=re.compile('领取奖励|領取獎勵')))
        def in_combat(*args,**kwargs):
            if self.combat_end_condition():
                return self.reset_to_false(reason='verified weekly boss victory')
            return originals['in_combat'](*args,**kwargs)
        self.in_combat=in_combat
        try:
            self.config.update(settings)
            record('batch_started',settings=settings,resumed_completed=progress.completed)
            if progress.pending:
                # Resume the same victory before any teleport or next combat.
                scene=resume_scene(self,pending=True)
                record('pending_pickup_resumed',scene=scene,round=progress.pending['round'],image=snap('pending-search'))
                self.load_chars()
                if self.in_combat():raise RuntimeError('Pending pickup search detected a new active battle')
                dropped=pick_echo() or self.walk_find_echo()
                incr_drop(dropped)
                battles[0]=progress.completed
                self.config['Repeat Farm Count']=20-progress.completed
            if progress.completed<20:original_run(self)
            if progress.completed!=20:raise RuntimeError('Native task returned before twenty verified round checkpoints')
            record('batch_succeeded',combats=progress.completed,progress_file=str(progress.path),absorb_actions=pickups[0],info=dict(self.info))
        except BaseException as exc:
            record('batch_failed',error=str(exc),image=snap('failure'))
            raise
        finally:
            stop.set();self.config.update(saved)
            self._cloud_weekly_trial=False
            for k,v in originals.items():setattr(self,k,v)
            self.executor.interaction.release_all()
    def run(self):
        from cloud_revive import revive_policy,recover_before_entry
        entry={'Teleport to Boss':'Weekly Challenge','Which Weekly Boss to Teleport':1,'Boss Level':'80'}
        try:
            with revive_policy(self,entry):
                try:
                    recovered=recover_before_entry(self)
                    if not recovered and os.environ.get('OKWW_BOSS_RESUME_HEAL')=='1':
                        from cloud_revive import world_heal_and_reenter
                        self.ensure_main(time_out=60)
                        # Entry belongs to run_impl, where verified warning handlers
                        # are installed. Preflight only verifies/restores health.
                        world_heal_and_reenter(self,reenter=False)
                except BaseException as exc:
                    image=f'{time.time_ns()}-preflight-failure.png'
                    cv2.imwrite(str(OUT/image),self.frame)
                    with (OUT/'events.jsonl').open('a',encoding='utf-8') as stream:
                        stream.write(json.dumps(dict(at=time.time(),event='batch_failed',
                            phase='revive_preflight',error=str(exc),image=image),ensure_ascii=False)+'\n')
                    raise
                return run_impl(self,recovered=recovered)
        finally:self.executor.interaction.release_all()
    FarmEchoTask.run=run
    from main_cloud_daily import main
    main(['--connect','--background','--allow-game-tasks','--task','echo'])


def nests_child(output):
    OUT=Path(output)
    import cv2
    import cloud_nest_current,cloud_nest_entry
    from cloud_nest_pickup import NestPickup
    class CatalogComplete(Exception):pass
    finished=[];catalog={};selected=[None];pickup_results={}
    def record(event,**data):
        with (OUT/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(at=time.time(),event=event,**data),ensure_ascii=False)+'\n')
    def snap(task,label):
        name=f'{time.time_ns()}-{label}.png';cv2.imwrite(str(OUT/name),task.frame);return name
    def select(task,allow_unfinished=False,hint=None):
        task.openF2Book('gray_book_boss');task.go_nest()
        ensure_nest_catalog(task)
        task.queues=[task.go_nest];task._nest_tab_of_current_nest='go_nest'
        task.swipe_relative(.973,.48,.973,.23,duration=.6);task.sleep(.4)
        task.sleep(.5)
        previous=None;stable=0
        for page in range(15):
            rows=[]
            for box in task.ocr(.35,.13,1,.96,match=task.count_re):
                value=cloud_nest_entry.count(box.name)
                if not value:continue
                h=task.height_of_screen(1)
                if box.y/h-.075 < .19:
                    continue  # Clipped row already covered by the overlapping previous page.
                rect=(.4,max(0,box.y/h-.075),.72,box.y/h-.018)
                names=[b.name.replace('像','象').strip() for b in task.ocr(*rect) if re.search(r'残[象像]聚落$',b.name.strip())]
                if len(names)!=1:raise RuntimeError('Nest catalog title unreadable')
                name=names[0];catalog[name]=value;rows.append((name,value))
                key=task._make_nest_cache_key(box,str(value[1]))
                eligible=name==hint['target'] if hint else allow_unfinished and value[0]<value[1]
                if not eligible:continue
                if name in finished:raise RuntimeError('Completed nest still appears unfinished')
                task.next_frame()
                second=cloud_nest_entry.count(''.join(b.name for b in task.ocr(.4,box.y/h-.007,.68,(box.y+box.height)/h+.007)))
                titles=[b.name.replace('像','象').strip() for b in task.ocr(*rect) if re.search(r'残[象像]聚落$',b.name.strip())]
                if second!=value or titles!=[name]:raise RuntimeError('Nest changed during verification')
                if selected[0] and selected[0]!=name:raise RuntimeError('Target changed before verified pickup')
                selected[0]=name
                record('selected',name=name,count=value,page=page,image=snap(task,'selected'))
                return box,key,name,value,second
            if not rows:raise RuntimeError('Empty catalog page cannot prove all nests complete')
            record('catalog_page',page=page,rows=rows,image=snap(task,'catalog'))
            stable=stable+1 if rows==previous else 0
            if stable>=2:
                if hint:raise RuntimeError('Pending nest missing from catalog')
                record('catalog_complete',catalog=catalog,finished=finished)
                raise CatalogComplete()
            previous=rows
            task.swipe_relative(.973,.52,.973,.83,duration=.6);task.sleep(.8)
        raise RuntimeError('Catalog scan limit reached without verified end')
    cloud_nest_entry.select=select
    native_install=cloud_nest_current.install
    def install(task,output,allow_unfinished=False):
        settings_path=Path(__file__).resolve().parent.parent/'okww-cloud-session/background/autorun-config.json'
        settings=json.loads(settings_path.read_text(encoding='utf-8'))
        task._cloud_nest_food_required=settings.get('nest_food_required',False) is True
        # Current user's Shanghai full workflow only; independent callers retain strict policy.
        task._cloud_nest_continue_unconfirmed=True
        task._cloud_nest_pickup_seconds=30
        def run():
            stop=threading.Event()
            def observe():
                while not stop.wait(.15):
                    try:
                        frame=task.executor.nullable_frame()
                        if frame is not None:
                            cv2.imwrite(str(OUT/'viewer-next.png'),frame,[cv2.IMWRITE_PNG_COMPRESSION,1]);os.replace(OUT/'viewer-next.png',OUT/'viewer.png')
                    except Exception:pass
            threading.Thread(target=observe,daemon=True).start()
            try:
                record('batch_started')
                for number in range(1,31):
                    selected[0]=None
                    task.info.pop('Nest Echo Collected',None)
                    task.info.pop('Nest Echo Search Completed',None)
                    task.info.pop('Nest Pickup Unconfirmed Allowed',None)
                    folder=OUT/f'nest-{number}';folder.mkdir()
                    native_install(task,folder,allow_unfinished=True)
                    one=task.run
                    try:one()
                    except CatalogComplete:
                        task.ensure_main(time_out=30)
                        record('batch_succeeded',finished=finished,catalog=catalog,pickup_results=pickup_results)
                        return
                    if task.info.get('Nest Echo Search Completed') is not True or not selected[0]:
                        raise RuntimeError('Nest returned without completed pickup search')
                    pickup_results[selected[0]]={'search_completed':True,
                        'absorbed':task.info.get('Nest Echo Collected') is True,
                        'unconfirmed_allowed':task.info.get('Nest Pickup Unconfirmed Allowed') is True,
                        'continuation_policy':__import__('cloud_nest_state').CLEARED_NEST_CONTINUATION_POLICY}
                    finished.append(selected[0]);record('nest_succeeded',name=selected[0],info=dict(task.info),image=snap(task,'completed'))
                raise RuntimeError('Nest batch safety limit reached')
            except BaseException as exc:
                record('batch_failed',error=str(exc),finished=finished,image=snap(task,'failure'));raise
            finally:stop.set();task.executor.interaction.release_all()
        task.run=run
    cloud_nest_current.install=install
    original_collect=NestPickup.collect
    def collect(self):
        record('pickup_started',image=snap(self.task,'pickup-start'))
        result=original_collect(self)
        record('pickup_finished',confirmed=self.confirmed,image=snap(self.task,'pickup-end'))
        return result
    NestPickup.collect=collect
    from main_cloud_daily import main
    main(['--connect','--background','--allow-game-tasks','--task','nightmare','--nest-current','--nest-unfinished'])

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',required=True,choices=('boss_echo','nest_echo'))
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not os.environ.get('OKWW_FULL_RUN_ID'):
        parser.error('This child requires its owning full-flow runner')
    (boss_child if args.stage=='boss_echo' else nests_child)(args.output)
