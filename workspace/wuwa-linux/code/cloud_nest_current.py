"""One named nest, using native combat/rotations and verified progress."""
import re
import time
from pathlib import Path
from cloud_nest_pickup import NestPickup, PickupNotConfirmed
from cloud_nest_state import NestState, pending_hint, OPTIONAL_PICKUP_TARGET, TERMINAL_PHASES, CLEARED_NEST_CONTINUATION_POLICY


class NestProgressLost(RuntimeError):
    """A nest objective is missing; only a verified same-nest return is allowed."""


class NestSearchCompleted(RuntimeError):
    """Exit the native pickup pipeline after a separately recorded empty search."""


def read_account(task):
    import cv2
    previous=None
    for _ in range(6):
        task.next_frame()
        enlarged=cv2.resize(task.frame,None,fx=3,fy=3)
        ids=re.findall(r'(?<!\d)\d{9}(?!\d)',''.join(
            b.name for b in task.ocr(1100/1280,697/720,1,1,frame=enlarged)))
        current=ids[0] if len(ids)==1 else None
        if current is not None and current==previous:return current
        previous=current;task.sleep(.2)
    raise RuntimeError('Game account identifier unreadable; no nest action')


def parse_progress(text, expected_total=41):
    if re.search(r'残[象像]聚落已(?:清剿|清理)', text):
        return (expected_total, expected_total)
    matches = re.findall(r'已击败残[象像]\s*[:：]?\s*(\d{1,2})\s*[/／]\s*(\d{1,2})', text)
    if len(matches) != 1:
        return None
    done, total = map(int, matches[0])
    return (done, total) if total == expected_total and 0 <= done <= total else None


class Progress:
    def __init__(self, task, total=41):
        self.task = task
        self.total = total
        self.value = None
        self.last_seen = None
        self.last_read = -10
        self.full_reads = 0
        self.complete = False
        self.changed = time.monotonic()
        self.book_count = None

    def read(self):
        now = time.monotonic()
        if self.complete or now-self.last_read < .5:
            return self.value
        self.last_read = now
        # A tracked story objective can move the real nest counter below .46.
        # Keep the left objective column and the same strict counter parser.
        text = ''.join(box.name for box in self.task.ocr(.005, .20, .29, .56))
        value = parse_progress(text, self.total)
        # Some verified nests show a textual objective instead of a counter.
        # Retain only the last known *incomplete* count; never invent kills.
        if value is None and re.search(r'(?:清理聚落中的残[象像]|清剿残[象像]聚落)',text):
            baseline = self.value or self.book_count
            if baseline is not None and 0 <= baseline[0] < self.total and baseline[1] == self.total:
                value = baseline
        if value is None or (self.value and value[0] < self.value[0]):
            self.full_reads = 0
            if self.last_seen is not None and now-self.last_seen > 15:
                raise NestProgressLost('Current nest progress unreadable for 15 seconds; no loot attempted')
            return self.value
        self.last_seen = now
        if value != self.value:
            self.changed = now
            self.task.log_info(f'CLOUD_NEST_PROGRESS {value[0]}/{value[1]}')
            self.task.info['Nest Verified Progress'] = f'{value[0]}/{value[1]}'
        self.value = value
        self.full_reads = self.full_reads+1 if value[0] == value[1] else 0
        self.complete = self.full_reads >= 2
        if not self.complete and now-self.changed > 180:
            raise RuntimeError('Current nest made no verified progress for 180 seconds')
        return value


def combat_until_verified(task, progress, native_once, *args, **kwargs):
    """Continue native combat while fresh counts progress, within a finite budget."""
    deadline = time.monotonic() + 900
    attempt = 0
    while not progress.complete:
        if time.monotonic() >= deadline:
            raise RuntimeError('Current nest exceeded 900 second combat budget; no loot attempted')
        result = native_once(*args, **kwargs)
        progress.read()
        if progress.complete:
            return result
        if progress.value is None:
            raise NestProgressLost('Nest progress not visible after entry; no loot attempted')
        if time.monotonic() - progress.changed > 180:
            raise RuntimeError('Current nest made no verified progress for 180 seconds')
        task.executor.interaction.release_all()
        attempt += 1
        task.log_info(f'CLOUD_NEST_RESUME unfinished={progress.value} attempt={attempt}')
        task.sleep(.5)


def run_native_nest(task, target, reenter, complete):
    for attempt in range(3):
        task.info.pop('Revive',None)
        try:
            task.combat_nest(target)
        except NestSearchCompleted:
            if not complete():raise RuntimeError('Empty search cannot finish incomplete combat')
            return
        except NestProgressLost:
            task.executor.interaction.release_all()
            task.reset_to_false(reason='nest objective lost; return to same verified nest')
            if attempt == 2:
                raise RuntimeError('Same-nest objective recovery retry limit reached')
            task.log_info(f'CLOUD_NEST_REENTER_AFTER_OBJECTIVE_LOSS attempt={attempt+1}')
            target=reenter()
            if complete():return
            continue
        if complete():
            return
        if task.info.get('Revive') != 'Success':
            raise RuntimeError('Native nest returned incomplete without verified revival')
        if attempt == 2:
            raise RuntimeError('Same-nest revival retry limit reached')
        task.log_info(f'CLOUD_NEST_REENTER_AFTER_NATIVE_REVIVE attempt={attempt+1}')
        target = reenter()
        if complete():
            return


def walk_verified_objective(task, progress, native_run):
    """One native forward approach to a fresh objective at the verified Blind nest."""
    if (task.info.get('Nest Target')!='盲望之塌残象聚落' or progress.total!=48
            or progress.book_count is None or not 0<=progress.book_count[0]<48):
        raise RuntimeError('Native objective approach lacks an exact unfinished book row')
    previous=[None]
    def objective():
        task.next_frame()
        text=''.join(b.name for b in task.ocr(.005,.20,.29,.56))
        value=parse_progress(text,progress.total)
        if value is None and re.search(r'(?:清理聚落中的残[象像]|清剿残[象像]聚落)',text):
            value=progress.book_count
        if value is not None and value==previous[0]:return value
        previous[0]=value
        return False
    from cloud_revive import recovery_navigation
    task.log_info('CLOUD_NEST_ENTRY native forward to two fresh verified Blind objectives')
    with recovery_navigation(task):
        result=native_run(objective,'w',time_out=14,running=False,target=False)
    if not result:
        raise NestProgressLost('Verified Blind forward approach found no objective')
    task.log_info(f'CLOUD_NEST_ENTRY objective verified {result}; native combat follows')
    task.next_frame();progress.last_read=-10;progress.read()
    if progress.value is None:
        raise NestProgressLost('Blind objective changed after entry approach')
    return result


def install(task, output, allow_unfinished=False):
    original_combat = task.in_combat
    original_end = task.combat_end_condition
    original_once = task.combat_once
    original_find_f = task.find_f_with_text
    original_pick_f = task.pick_f
    original_pick_echo = task.pick_echo
    original_walk_find_echo = task.walk_find_echo
    original_run_until = task.run_until
    progress = Progress(task)
    receipt = None
    at_entry = False
    read_progress = progress.read
    def save_progress():
        was_complete = progress.complete
        value = read_progress()
        if progress.complete and not was_complete and receipt is not None:
            receipt.cleared()
        return value
    progress.read = save_progress
    def native_approach():
        nonlocal at_entry
        def walk():
            task.log_info(f'CLOUD_NEST_NATIVE_APPROACH at_entry={at_entry}')
            if at_entry:
                # Restore the native post-teleport run before backward/forward
                # searching, but stop immediately if an absorb prompt appears.
                task.run_until(pickup.prompt, 'w', time_out=2, running=True)
                if pickup.prompt():
                    return True
            return task.walk_until_f(time_out=5, backward_time=0 if not at_entry else 2.5,
                                     target_text=task.absorb_echo_text(), raise_if_not_found=False,
                                     check_combat=False)
        return walk()
    def return_to_same_nest():
        nonlocal at_entry
        # Bounded fallback, also available when resuming a pending pickup.
        from cloud_nest_entry import select
        from src.task.NightmareNestTask import NestTarget
        box,key,name,first,second = select(task,False,receipt.record)
        if name != receipt.scope['target'] or first != (progress.total,progress.total) or first != second:
            raise RuntimeError('Same-nest pickup return not verified')
        box.x=task.width_of_screen(.9);box.y-=box.height*.9
        box.width=box.height=1
        target=NestTarget(box,key)
        task.click(target.box,after_sleep=2)
        if not task._travel_to_nest_or_skip(target):
            raise RuntimeError('Same-nest pickup return failed')
        at_entry=True
    def searched_empty():
        # Absence is a search result, never an absorption receipt. Require
        # fresh world completion, the same UID, and a twice-read named row.
        import cv2,hashlib
        from cloud_nest_entry import select
        task.next_frame()
        team,index,count=task.in_team()
        if (parse_progress(''.join(b.name for b in task.ocr(.005,.20,.29,.46)),progress.total)
                !=(progress.total,progress.total) or not team or count!=3):
            raise RuntimeError('Empty search lacks fresh cleared-nest world evidence')
        if hashlib.sha256(read_account(task).encode()).hexdigest()!=receipt.scope['account']:
            raise RuntimeError('Empty search account changed')
        image=Path(output)/f'pickup-{time.time_ns()}-searched-no-echo.png'
        cv2.imwrite(str(image),task.frame)
        box,key,name,first,second=select(task,False,receipt.record)
        if name!=receipt.scope['target'] or first!=second or first!=(progress.total,progress.total):
            raise RuntimeError('Empty search named completion changed')
        receipt.searched_empty(dict(target=name,count=list(first),absorb_sent=False,stable_target_seen=False,
            native_circle_completed=True,verified_at=time.time(),image=str(image),
            image_sha256=hashlib.sha256(image.read_bytes()).hexdigest()))
        task.send_key('esc',after_sleep=.5)
    def unconfirmed_allowed(search):
        continue_cleared=getattr(task,'_cloud_nest_continue_unconfirmed',False) is True
        if receipt is None or (not continue_cleared and receipt.scope['target']!=OPTIONAL_PICKUP_TARGET):
            return False
        if receipt.scope['day']!=__import__('cloud_nest_state').game_day():
            raise RuntimeError('Final-nest pickup crossed the game-day boundary')
        import cv2,hashlib
        from cloud_nest_entry import select
        task.next_frame()
        team,index,count=task.in_team()
        if not progress.complete or not team or count!=3:
            raise RuntimeError('Final-nest continuation requires completion and a fresh team')
        if hashlib.sha256(read_account(task).encode()).hexdigest()!=receipt.scope['account']:
            raise RuntimeError('Final-nest continuation account changed')
        image=Path(output)/f'pickup-{time.time_ns()}-unconfirmed-allowed.png'
        cv2.imwrite(str(image),task.frame)
        box,key,name,first,second=select(task,False,receipt.record)
        if name!=receipt.scope['target'] or first!=second or first!=(progress.total,progress.total):
            raise RuntimeError('Cleared-nest named completion not verified')
        proof=dict(target=name,count=list(first),absorb_sent=search.absorb_sent,
            bounded_search_completed=True,verified_at=time.time(),image=str(image),
            image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        if continue_cleared:
            proof['user_policy']=CLEARED_NEST_CONTINUATION_POLICY
            receipt.continue_after_search(proof)
        else:
            proof['user_policy']='final_nest_ignore_unconfirmed_absorption'
            receipt.unconfirmed_allowed(proof)
        task.info['Nest Pickup Unconfirmed Allowed']=True
        task.send_key('esc',after_sleep=.5)
        return True
    pickup = NestPickup(task, lambda: progress.complete, original_find_f,
                        on_confirmed=lambda: receipt.picked(), native_approach=native_approach,
                        return_to_same_nest=return_to_same_nest, output=output,
                        native_circle=lambda:task.run_in_circle_to_find_echo(circle_count=1 if getattr(task,'_cloud_nest_continue_unconfirmed',False) is True else 3),
                        on_searched_empty=searched_empty,on_unconfirmed_allowed=unconfirmed_allowed,
                        on_target_seen=lambda first,second: receipt.target_seen(first,second))

    def find_f(target_text=None):
        if progress.complete and target_text is not None and target_text.search('吸收'):
            return pickup.prompt()
        return original_find_f(target_text)

    def pick_f(handle_claim=True):
        if progress.complete:return absorb_or_continue()
        return original_pick_f(handle_claim)

    def pick_echo():
        if progress.complete:return absorb_or_continue()
        return original_pick_echo()

    def absorb_or_continue():
        try:return pickup.absorb()
        except PickupNotConfirmed:
            if pickup.finish_unconfirmed():raise NestSearchCompleted()
            raise

    def walk_find_echo(*args, **kwargs):
        if progress.complete:
            collected=pickup.collect()
            if not collected and pickup.search_completed:raise NestSearchCompleted()
            return collected
        return original_walk_find_echo(*args, **kwargs)

    def in_combat(*args, **kwargs):
        value = progress.read()
        if value is None:
            # Some nests first show only "clear the nest". Use native enemy
            # detection until a numeric objective appears; this cannot certify
            # completion and leaves the existing progress checks in force.
            return original_combat(*args, **kwargs)
        if progress.complete:
            return task.reset_to_false(reason='current nest full progress verified twice')
        result = original_combat(*args, **kwargs)
        if result or value is None:
            return result
        ok, index, count = task.in_team()
        # Retain native death/popup handling; do not pretend a hidden HUD is alive.
        if ok and count == 3:
            if not task.get_current_char():
                task.load_chars()
            task._in_combat = True
            return task.scene.set_in_combat()
        return False

    def run():
        nonlocal receipt, at_entry
        import cv2
        from src.task.WWOneTimeTask import WWOneTimeTask
        WWOneTimeTask.run(task)
        task.ensure_main(time_out=30)
        # Re-check account and the same named book row even after reconnect.
        # A vanished world objective is not evidence that completion was lost.
        accounts = [read_account(task)]
        from cloud_nest_entry import select
        from src.task.NightmareNestTask import NestTarget
        import hashlib
        state_dir = Path(__file__).resolve().parent.parent/'okww-cloud-session/background'
        hint = pending_hint(state_dir, accounts[0])
        box, key, name, first_count, second_count = select(task, allow_unfinished, hint)
        progress.total = first_count[1]
        progress.book_count = first_count
        ident = hashlib.sha256(name.encode()).hexdigest()[:12]
        state_path = state_dir/f'nest-state-{ident}.json'
        receipt = NestState(state_path, accounts[0], target=name, key=key, total=progress.total)
        phase = receipt.reconcile(name, first_count, second_count)
        pickup.target_seen = bool(receipt.record.get('unclaimed_target_seen'))
        task.info['Nest Target'] = name
        task.log_info(f'CLOUD_NEST_RECEIPT target={name} phase={phase} live_count={first_count}')
        cv2.imwrite(str(output/'nest-current-target.png'),task.frame)
        if phase in TERMINAL_PHASES:
            task.send_key('esc', after_sleep=.5)
            task.info['Nest Echo Collected'] = phase=='PICKED_UP'
            task.info['Nest Echo Search Completed'] = True
            task.info['Nest Pickup Unconfirmed Allowed'] = phase=='PICKUP_UNCONFIRMED_ALLOWED'
            task.log_info('CLOUD_NEST_ALREADY_VERIFIED no repeat combat or pickup')
            return
        if first_count[0] == first_count[1]:
            progress.value = first_count
            progress.complete = True
            task.info['Nest Verified Progress'] = f'{first_count[0]}/{first_count[1]}'
            task.log_info(f'CLOUD_NEST_PROGRESS {first_count} verified again in same named book row')
        elif getattr(task,'_cloud_nest_food_required',False):
            from cloud_food import prepare
            prepare(task,output)
            box,key,new_name,first,second=select(task,False,receipt.record)
            if new_name!=name or first!=first_count or second!=second_count:
                raise RuntimeError('Nest identity/progress changed after food preparation')
        box.x=task.width_of_screen(.9);box.y-=box.height*.9
        box.width=box.height=1
        target=NestTarget(box,key)
        cv2.imwrite(str(output/'nest-current-start.png'),task.frame)
        task.load_chars()
        task.in_combat = in_combat
        task.find_f_with_text = find_f
        task.pick_f=pick_f
        task.pick_echo=pick_echo
        task.walk_find_echo=walk_find_echo
        task.combat_end_condition = lambda: (progress.read() is not None and progress.complete)
        def verified_run_until(condition,direction,time_out,raise_if_not_found=False,running=False,target=False,post_walk=0):
            if (name=='盲望之塌残象聚落' and condition is in_combat and direction=='w'
                    and time_out==10 and target and not running and progress.value is None):
                return walk_verified_objective(task,progress,original_run_until)
            return original_run_until(condition,direction,time_out,raise_if_not_found=raise_if_not_found,
                                      running=running,target=target,post_walk=post_walk)
        task.run_until=verified_run_until
        def verified_combat(*args, **kwargs):
            return combat_until_verified(task,progress,original_once,*args,**kwargs)
        task.combat_once=verified_combat
        try:
            if progress.value == (progress.total, progress.total):
                task.wait_until(lambda: (progress.read() is not None and progress.complete),time_out=3)
            if target is not None and progress.complete:
                task.click(target.box,after_sleep=2)
                if not task._travel_to_nest_or_skip(target):
                    raise RuntimeError('Could not return to the completed nest for pickup')
                task.load_chars()
                at_entry=True
                # Inspect the arrival position before any pickup movement.
            elif target is not None:
                def reenter():
                    nonlocal at_entry
                    box,key,name,first,second = select(task,False,receipt.record)
                    if name != receipt.scope['target']:
                        raise RuntimeError('Revival return target changed')
                    receipt.reconcile(name,first,second)
                    # Fresh named book proof replaces the abandoned area's
                    # cached count. It never infers victory from missing HUD.
                    progress.value=first if first==(progress.total,progress.total) else None
                    progress.book_count=first
                    progress.last_seen=None
                    progress.last_read=-10
                    progress.full_reads=0
                    progress.changed=time.monotonic()
                    progress.complete=first==(progress.total,progress.total)
                    box.x=task.width_of_screen(.9);box.y-=box.height*.9
                    box.width=box.height=1
                    resumed=NestTarget(box,key)
                    if first == (progress.total,progress.total):
                        progress.value=first
                        progress.complete=True
                        task.click(resumed.box,after_sleep=2)
                        if not task._travel_to_nest_or_skip(resumed):
                            raise RuntimeError('Completed nest revival return failed')
                        task.load_chars()
                        at_entry=True
                    return resumed
                run_native_nest(task,target,reenter,lambda:progress.complete)
                if progress.complete and not pickup.confirmed:
                    pickup.collect()
                if not progress.complete or not pickup.search_completed:
                    raise RuntimeError('Native nest return did not verify both completion and echo pickup')
                task.info['Nest Echo Collected']=pickup.confirmed
                task.info['Nest Echo Search Completed']=True
                cv2.imwrite(str(output/'nest-current-completed.png'),task.frame)
                task.log_info('CLOUD_NEST_CURRENT_SUCCEEDED one nest only')
                return
            # Native combat_once and character perform methods remain unchanged.
            combat_until_verified(task,progress,original_once,wait_combat_time=10,target=True,raise_if_not_found=False)
            cv2.imwrite(str(output/'nest-current-41of41.png'),task.frame)
            task.reset_to_false(reason='verified nest completed before pickup')
            captured = pickup.collect()
            task.info['Nest Echo Collected'] = bool(captured)
            task.info['Nest Echo Search Completed'] = pickup.search_completed
            if not pickup.search_completed:
                raise RuntimeError('Nest complete but echo pickup not verified')
            cv2.imwrite(str(output/'nest-current-completed.png'),task.frame)
            task.log_info('CLOUD_NEST_CURRENT_SUCCEEDED one nest only')
        finally:
            task.in_combat = original_combat
            task.combat_end_condition = original_end
            task.combat_once = original_once
            task.find_f_with_text=original_find_f
            task.pick_f=original_pick_f
            task.pick_echo=original_pick_echo
            task.walk_find_echo=original_walk_find_echo
            task.run_until=original_run_until
            task.executor.interaction.release_all()
    task.run = run
