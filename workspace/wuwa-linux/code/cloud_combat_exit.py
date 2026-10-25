"""Browser combat-exit cleanup; upstream rotations and combat loop stay intact."""
def close_echo_reward_overlay(task):
    """Only cancel a positively matched claim overlay; never confirm rewards."""
    if not getattr(task,'_cloud_echo_only',False) or not task.has_claim():
        return False
    release(task,'echo_reward_overlay_cancel')
    task.send_key('esc',after_sleep=0)
    task.log_info('CLOUD_ECHO cancelled native claim overlay; observe victory without spending')
    task.next_frame()
    return True


def retry_missing_team(task, elapsed):
    recovery = getattr(task, '_cloud_weekly_handle_revive', None)
    if recovery:
        recovery()
    if task.is_browser() and close_echo_reward_overlay(task):
        return True
    if not task.is_browser() or not task.cloud_domain_still_active():
        return False
    if getattr(task,'_cloud_weekly_trial',False):
        import time
        release(task,'weekly_cinematic_wait')
        deadline=time.monotonic()+35
        while time.monotonic()<deadline:
            task.next_frame()
            if recovery:
                recovery()
            if close_echo_reward_overlay(task):
                return True
            ok,index,count=task.in_team()
            if ok and count==3:
                task.log_info('CLOUD_WEEKLY cinematic ended; team HUD restored')
                return True
            time.sleep(.1)
        raise RuntimeError('Weekly team HUD did not return within 35 seconds')
    if elapsed > task.switch_char_time_out:
        raise RuntimeError('Cloud team recognition timed out during active combat')
    task.log_info('CLOUD_SWITCH team HUD obscured during active domain; observe next frame')
    task.next_frame()
    return True


def release(task, stage):
    interaction = task.executor.interaction
    task.log_info(f'CLOUD_EXIT {stage} held_keys={sorted(interaction.held_keys)} '
                  f'held_buttons={sorted(interaction.held_buttons)}')
    interaction.release_all()


def prepare_loot(task):
    release(task, 'before_loot')
    # Do not trust the cached active character after a combat-end exception.
    def observed():
        ok, index, count = task.in_team()
        return index if ok and count == 3 else None
    index = observed()
    if index is None:
        raise RuntimeError('Cannot verify active character before reward walking')
    for char in task.chars:
        if char:
            char.is_current_char = char.index == index
    current = task.chars[index]
    if type(current).__name__ == 'Mornye':
        current.switch_other_char(allow_auto_combat=True)
        task.sleep(2)
        fresh = observed()
        if fresh is None or fresh == index:
            raise RuntimeError('Mornye exit switch was not confirmed')
        task.log_info(f'CLOUD_EXIT reward walker switched from Mornye to slot {fresh + 1}')
    release(task, 'ready_for_loot')


def install():
    from src.task.BaseCombatTask import BaseCombatTask
    from src.task.BaseWWTask import BaseWWTask
    if getattr(BaseCombatTask, '_cloud_exit_cleanup', False):
        return
    original_end = BaseCombatTask.combat_end
    original_walk = BaseWWTask.walk_to_treasure

    def end(self):
        if not self.is_browser():
            return original_end(self)
        release(self, 'combat_end')
        try:
            from cloud_material_combat import applies, require_completion
            if applies(self):
                require_completion(self, 'combat_end')
            return original_end(self)
        finally:
            release(self, 'after_combat_cleanup')

    def walk(self, *args, **kwargs):
        if self.is_browser():
            from cloud_material_combat import applies, require_completion
            if applies(self):
                release(self, 'verify_completion_before_loot')
                require_completion(self, 'reward_walk')
            prepare_loot(self)
            if applies(self):
                from cloud_loot import navigate_confirmed_reward
                # The native generic-F pass misses the compressed F glyph after
                # the claim-text pass already succeeded, walking past the tree.
                # Reach the positively identified prompt once; native pick_f
                # below remains responsible for opening and verifying the dialog.
                return navigate_confirmed_reward(self,
                    lambda: original_walk(self, send_f=False, raise_if_not_found=kwargs.get('raise_if_not_found', True)))
        return original_walk(self, *args, **kwargs)

    BaseCombatTask.combat_end = end
    BaseWWTask.walk_to_treasure = walk
    BaseCombatTask._cloud_exit_cleanup = True
