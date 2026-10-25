"""Browser boss loot: native Walk first, then one bounded YOLO search."""
import time

SEARCH_SECONDS = 10.0


def search(task):
    """Share one deadline across detection, turns, movement and interaction.

    Native detector and steering geometry are retained. Movement uses short
    released pulses so OCR/model calls never run with a movement key held.
    In-flight capture/OCR/transport calls can finish after the deadline, but
    their late results cannot authorize another input action.
    """
    started = time.monotonic()
    deadline = started + SEARCH_SECONDS
    interaction = task.executor.interaction
    result = 'timeout'
    scans = 0
    last_direction = None

    def remaining():
        return max(0.0, deadline - time.monotonic())

    def pulse(key, seconds):
        if remaining() <= 0:
            return False
        try:
            task.send_key_down(key)
            time.sleep(min(seconds, remaining()))
        finally:
            task.send_key_up(key)
        return True

    task.log_info('CLOUD_ECHO fallback_started budget=10s')
    try:
        interaction.release_all()
        while remaining() > 0:
            task.next_frame()
            if remaining() <= 0:
                break
            if task.in_combat():
                result = 'combat_resumed'
                break
            if remaining() <= 0:
                break
            # A YOLO box alone must never authorize F (claim/exit can be nearby).
            absorb = task.find_f_with_text(target_text=task.absorb_echo_text())
            if remaining() <= 0:
                break
            if absorb:
                if not pulse('f', .05):
                    break
                result = 'absorb_sent'
                return True
            echoes = task.find_echos(threshold=task.yolo_threshold)
            if remaining() <= 0:
                break
            if not echoes:
                # Native YOLO search turns by tapping left then centering camera.
                # Limit sweeps as well as elapsed time; never wander indefinitely.
                if scans >= 4:
                    result = 'no_target'
                    break
                scans += 1
                if not pulse('a', .05):
                    break
                if remaining() < .1:
                    break
                task.middle_click(down_time=.05, after_sleep=0)
                last_direction = None
                continue
            echo = echoes[0]
            offset = echo.center()[0] - task.width_of_screen(.5)
            tolerance = task.height_of_screen(.05 if last_direction is None else .15)
            if abs(offset) < tolerance:
                direction = 's' if echo.y + echo.height > task.height_of_screen(.65) else 'w'
            else:
                direction = 'd' if offset > 0 else 'a'
            if not pulse(direction, .15):
                break
            last_direction = direction
        return False
    except BaseException:
        result = 'error'
        raise
    finally:
        interaction.release_all()
        task.log_info(f'CLOUD_ECHO fallback_finished result={result} elapsed={time.monotonic()-started:.2f}s')


def install():
    from src.task.FarmEchoTask import FarmEchoTask
    if getattr(FarmEchoTask, '_cloud_echo_pickup', False):
        return
    native_walk = FarmEchoTask.walk_find_echo

    def walk(self, *args, **kwargs):
        found = native_walk(self, *args, **kwargs)
        if found or not self.is_browser() or self.config.get('Echo Pickup Method', 'Walk') != 'Walk':
            return found
        return search(self)

    FarmEchoTask.walk_find_echo = walk
    FarmEchoTask._cloud_echo_pickup = True
