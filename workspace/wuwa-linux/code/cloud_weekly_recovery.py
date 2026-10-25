"""Bounded weekly-only recovery around the unchanged native combat routines."""
import re
from contextlib import contextmanager


class ResumeWeeklyCombat(RuntimeError):
    pass


def active_objective(task):
    return bool(task.ocr(.01, .21, .25, .31, match=re.compile('击败敌人|擊敗敵人')))


def revive_popup(task):
    return bool(task.ocr(.18, .14, .5, .25, match=re.compile('选择复苏物品|選擇復甦物品')))


@contextmanager
def recovery(task, *, active_check=None):
    names = ('combat_once', '_choose_switch_target', 'switch_next_char',
             'raise_not_in_combat', 'get_current_char')
    originals = {name: getattr(task, name) for name in names}
    own = {name: task.__dict__.get(name) for name in names}
    dead = set()
    switching = [False, None]

    def recover_dead(target=None):
        from cloud_revive import medicine_or_heal
        method=medicine_or_heal(task,target)
        dead.clear()
        task.reset_to_false(reason='death recovered with '+method)
        task.load_chars()
        task.log_info('CLOUD_WEEKLY_RECOVER verified '+method+'; resume native rotation')
        raise ResumeWeeklyCombat('Death recovered; continue native combat')

    def handle_popup():
        if not revive_popup(task):
            return False
        from cloud_combat_exit import release
        release(task, 'weekly_revive_popup')
        target = switching[1] if switching[0] else None
        if getattr(task,'_cloud_use_revive_medicine',False):
            recover_dead(target)
        task.close_revive_popup()
        if not task.wait_until(lambda: task.in_team()[0], time_out=5):
            raise RuntimeError('Weekly death recovery: no surviving team HUD')
        ok, index, count = task.in_team()
        if target is not None and index != target:
            dead.add(target)
            task.log_info(f'CLOUD_WEEKLY_DEAD confirmed slot={target + 1}; surviving slot={index + 1}')
        else:
            task.log_info('CLOUD_WEEKLY_RECOVER closed revive prompt; no slot inferred')
        if index in dead or count != 3:
            raise RuntimeError('Weekly death recovery: inconsistent surviving team')
        task.load_chars()
        raise ResumeWeeklyCombat('Revive popup closed; continue with surviving characters')

    def choose(current, has_intro, target_low_con=False):
        chars = task.chars
        try:
            task.chars = [None if char and char.index in dead else char for char in chars]
            result = originals['_choose_switch_target'](current, has_intro, target_low_con=target_low_con)
        finally:
            task.chars = chars
        if switching[0]:
            switching[1] = result.index if result and result != current else None
        return result

    def switch(*args, **kwargs):
        switching[:] = [True, None]
        try:
            return originals['switch_next_char'](*args, **kwargs)
        finally:
            switching[:] = [False, None]

    def raise_not(message):
        handle_popup()
        try:return originals['raise_not_in_combat'](message)
        except Exception as exc:
            if type(exc).__name__!='CharDeadException' or not getattr(task,'_cloud_use_revive_medicine',False):raise
            recover_dead(switching[1] if switching[0] else None)

    def current(*args, **kwargs):
        ok, index, count = task.in_team()
        if ok and count == 3:
            for char in task.chars:
                if char:
                    char.is_current_char = char.index == index
        return originals['get_current_char'](*args, **kwargs)

    def combat(*args, **kwargs):
        # Do not proceed to echo/reward navigation until the victory objective.
        for attempt in range(5):
            try:
                # Native combat may return directly without raising its usual
                # switch/not-in-combat exception while a revive dialog is open.
                # Its blurred background cannot be used as objective evidence.
                handle_popup()
                try:
                    result = originals['combat_once'](*args, **kwargs)
                except Exception as exc:
                    if type(exc).__name__!='CharDeadException' or not getattr(task,'_cloud_use_revive_medicine',False):raise
                    recover_dead()
                handle_popup()
            except ResumeWeeklyCombat:
                task.log_info(f'CLOUD_WEEKLY_RESUME after_revive_popup attempt={attempt + 1}')
                continue
            if task.wait_until(task.combat_end_condition, time_out=2):
                return result
            if not (active_objective(task) or (active_check is not None and active_check())):
                raise RuntimeError('Weekly combat ended without verified active or completed objective')
            from cloud_combat_exit import release
            release(task, 'weekly_resume_combat')
            task.load_chars()
            task.log_info(f'CLOUD_WEEKLY_RESUME attempt={attempt + 1} excluded_slots={sorted(i + 1 for i in dead)}')
        raise RuntimeError('Weekly combat recovery exhausted; no reward claimed')

    task.combat_once = combat
    task._choose_switch_target = choose
    task.switch_next_char = switch
    task.raise_not_in_combat = raise_not
    task.get_current_char = current
    task._cloud_weekly_handle_revive = handle_popup
    try:
        yield
    finally:
        for name in names:
            if own[name] is None:
                task.__dict__.pop(name, None)
            else:
                setattr(task, name, own[name])
        task.__dict__.pop('_cloud_weekly_handle_revive', None)
