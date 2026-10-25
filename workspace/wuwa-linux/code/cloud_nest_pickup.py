"""Bounded pickup for the verified current nest; no combat or progress decisions."""
import re
import time


class PickupNotConfirmed(RuntimeError):
    """A bounded search may recover this, but it never proves collection."""


class PickupSearchEmpty(PickupNotConfirmed):
    """No absorb action was sent; a bounded native circle may search another side."""


class PickupTargetNotReached(PickupSearchEmpty):
    """A stable target remains uncollected; native search may continue, never empty-proof."""


class NestPickup:
    def __init__(self, task, complete, native_find_f, on_confirmed=None, native_approach=None,
                 return_to_same_nest=None, output=None, native_circle=None, on_searched_empty=None,
                 on_unconfirmed_allowed=None, on_target_seen=None):
        self.task = task
        self.complete = complete
        self.native_find_f = native_find_f
        self.confirmed = False
        self.on_confirmed = on_confirmed
        self.native_approach = native_approach
        self.return_to_same_nest = return_to_same_nest
        self.output = output
        self.native_circle = native_circle
        self.on_searched_empty = on_searched_empty
        self.search_completed = False
        self.absorb_sent = False
        self.target_seen = False
        self.on_target_seen = on_target_seen
        self.on_unconfirmed_allowed = on_unconfirmed_allowed

    def finish_unconfirmed(self):
        if self.search_completed:
            return not self.confirmed
        if self.on_unconfirmed_allowed is None or not self.on_unconfirmed_allowed(self):
            return False
        self.search_completed = True
        self.task.log_info('CLOUD_NEST_PICKUP_UNCONFIRMED_ALLOWED user policy; no absorption claim')
        return True

    def snapshot(self, label):
        if self.output is not None:
            import cv2
            path = self.output/f'pickup-{time.time_ns()}-{label}.png'
            if not cv2.imwrite(str(path), self.task.frame):
                raise RuntimeError('Pickup evidence image could not be saved')
            return path

    def prompt(self):
        if not self.complete():
            return False
        if self.native_find_f(re.compile(r'^(吸收|Absorb)$', re.I)):
            self.task.executor.interaction.release_all()
            return True
        boxes = self.task.ocr(.6, .32, .98, .68, match=re.compile(r'^吸收$'))
        if len(boxes) == 1:
            self.task.executor.interaction.release_all()
            return True
        return False

    def absorb(self, input_deadline=None):
        if self.confirmed:
            return True
        if not self.prompt():
            return False
        self.task.executor.interaction.release_all()
        self.task.sleep(.25)
        self.task.next_frame()
        if not self.prompt():
            return False
        # One retry only while the exact absorb prompt is still present.
        for attempt in range(2):
            if input_deadline is not None and time.monotonic() >= input_deadline:
                return False
            self.task._capture_success = False
            self.snapshot(f'before-f-{attempt+1}')
            self.absorb_sent = True
            self.task.send_key('f', down_time=.10, after_sleep=.15)
            def notification():
                self.task.next_frame()
                found = self.task.has_echo_notification()
                self.snapshot('confirmed' if found else 'notification-check')
                return found
            if self.task.wait_until(notification, time_out=5):
                self.confirmed = True
                self.search_completed = True
                if self.on_confirmed:
                    self.on_confirmed()
                self.task.log_info('CLOUD_NEST_ECHO_NOTIFICATION confirmed after absorb')
                return True
            self.task.next_frame()
            if not self.prompt():
                # Cloud absorption can hide F before its success toast arrives.
                # Observe only: never infer collection from disappearance and
                # never send another F while the exact prompt is absent.
                self.task.log_info('CLOUD_NEST_PICKUP prompt gone; observe native notification up to 15s')
                if self.task.wait_until(notification, time_out=15):
                    self.confirmed = True
                    self.search_completed = True
                    if self.on_confirmed:
                        self.on_confirmed()
                    self.task.log_info('CLOUD_NEST_ECHO_NOTIFICATION confirmed after delayed cloud response')
                    return True
                break
            if attempt:
                break
            self.task.log_info('CLOUD_NEST_PICKUP retry F after fresh absorb prompt')
        raise PickupNotConfirmed('Absorb sent but echo notification not verified; pickup stopped')

    def _detect(self):
        from ok import og
        from cloud_nest_candidates import usable
        # Keep the native threshold; lowering it admitted the player's body.
        frame = self.task.frame
        return [b for b in og.my_app.yolo_detect(frame, threshold=.5, label=0)
                if usable(frame,b)]

    @staticmethod
    def same_target(a, b):
        left, top = max(a.x, b.x), max(a.y, b.y)
        right = min(a.x+a.width, b.x+b.width)
        bottom = min(a.y+a.height, b.y+b.height)
        intersection = max(0, right-left)*max(0, bottom-top)
        union = a.width*a.height+b.width*b.height-intersection
        return union > 0 and intersection/union >= .5

    def collect(self):
        if self.search_completed:
            return self.confirmed
        try:
            return self._collect()
        except PickupNotConfirmed:
            if self.finish_unconfirmed():
                return False
            raise

    def _collect(self):
        try:
            return self._search()
        except PickupSearchEmpty:
            # Search the actual kill position before a teleport changes it.
            # A sent F without a notification remains ambiguous and stops.
            if self.absorb_sent:
                raise
            if self.native_circle is not None:
                try:
                    self.task.log_info('CLOUD_NEST_PICKUP native circle before same-nest return')
                    self.native_circle()
                    if self.confirmed:
                        return True
                finally:
                    self.task.executor.interaction.release_all()
            if self.return_to_same_nest is None:
                raise
            self.task.log_info('CLOUD_NEST_PICKUP recovery: re-verify and return to same cleared nest once')
            self.return_to_same_nest()
            try:
                return self._search()
            except PickupSearchEmpty:
                if getattr(self.task,'_cloud_nest_continue_unconfirmed',False) is True:
                    # The authorized callback verifies the named book row even
                    # if the cleared world's objective has disappeared.
                    raise PickupSearchEmpty('Bounded same-nest search exhausted; verify continuation')
                if (self.on_searched_empty is not None and self.native_circle is not None
                        and not self.absorb_sent and not self.target_seen):
                    self.on_searched_empty()
                    self.search_completed = True
                    self.task.log_info('CLOUD_NEST_SEARCH_COMPLETED no echo found; absorption NOT confirmed')
                    return False
                raise PickupSearchEmpty('Same-nest search completed without verified echo pickup')

    def _search(self):
        if not self.complete():
            raise RuntimeError('Pickup requires verified nest completion')
        task = self.task
        try:
            task.executor.interaction.release_all()
            # Let combat effects settle in place. Never move before checking F.
            for _ in range(6):
                task.next_frame()
                if self.absorb():
                    return True
                task.sleep(.5)
            # The native task walks to an interaction before relying on YOLO.
            # Distant gold outlines need not be model-detectable to find F.
            if self.native_approach:
                self.native_approach()
                task.next_frame()
                if self.absorb():
                    return True
            # Walking and teleporting cannot consume the YOLO time allowance.
            budget=getattr(task,'_cloud_nest_pickup_seconds',90)
            if budget not in (30,90):raise RuntimeError('Unsupported nest pickup budget')
            deadline = time.monotonic()+budget
            task.log_info(f'CLOUD_NEST_PICKUP YOLO started budget={budget}s max_steps=30')
            scans = 0
            for _ in range(30):
                if time.monotonic() >= deadline:
                    break
                task.next_frame()
                if self.absorb(input_deadline=deadline):
                    return True
                first = self._detect()
                first_image = self.snapshot('detect-first')
                task.sleep(.15)
                task.next_frame()
                if self.absorb(input_deadline=deadline):
                    return True
                second = self._detect()
                second_image = self.snapshot('detect-second')
                stable = [b for b in second if any(self.same_target(a, b) for a in first)]
                if not stable:
                    if scans >= 3:
                        break
                    scans += 1
                    task.log_info(f'CLOUD_NEST_PICKUP scan={scans} no stable target')
                    # Native camera recenter/short turn, without a blind run or
                    # teleport that would discard the current drop position.
                    if time.monotonic() >= deadline:
                        break
                    task.turn_direction('a')
                    continue
                # Three misses must be consecutive, not accumulated across targets.
                scans = 0
                target = max(stable, key=lambda b: b.confidence)
                if not self.target_seen and self.on_target_seen is not None:
                    self.on_target_seen(first_image, second_image)
                self.target_seen = True
                delta = target.x+target.width/2-task.width_of_screen(.5)
                direction = ('d' if delta > 0 else 'a') if abs(delta) > task.width_of_screen(.08) else 'w'
                if time.monotonic() >= deadline:
                    break
                task.log_info(f'CLOUD_NEST_PICKUP step={direction} confidence={target.confidence:.3f}')
                task.send_key(direction, down_time=.18, after_sleep=.15)
                # Recenter after a lateral pulse, as the native search does.
                # Strafing alone loses a distant drop from the camera view.
                if direction in ('a','d') and time.monotonic() < deadline:
                    task.center_camera()
                # A new pair of observations is required for every further step.
            task.next_frame()
            if time.monotonic() < deadline:
                if self.absorb(input_deadline=deadline):
                    return True
            elif not self.absorb_sent and self.prompt():
                # A final movement can reveal F just as the movement budget
                # expires. Stay in place: the existing absorb routine still
                # requires a second fresh prompt and the native notification.
                task.log_info('CLOUD_NEST_PICKUP stationary final prompt check after movement deadline')
                self.snapshot('deadline-prompt')
                if self.absorb(input_deadline=time.monotonic()+5):
                    return True
            if self.target_seen:
                raise PickupTargetNotReached('Echo target seen but no verified pickup within bounded search; stopped')
            raise PickupSearchEmpty('No verified echo pickup within bounded search; stopped in current nest')
        finally:
            task.executor.interaction.release_all()
