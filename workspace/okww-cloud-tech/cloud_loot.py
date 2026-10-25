"""Browser-only reward text fallback; leave upstream walking and combat intact."""
import re


def navigate_confirmed_reward(task, native_walk):
    """Called only after the material completion gate; never grants combat exit."""
    task._cloud_reward_navigation = True
    try:
        return native_walk()
    finally:
        task._cloud_reward_navigation = False
        task.executor.interaction.release_all()


def claim_prompt(task):
    boxes = task.ocr(.64,.36,.94,.65,match=re.compile('领取奖励|領取獎勵|Claim Rewards',re.I))
    return boxes[0] if boxes else None


def install():
    from src.task.BaseWWTask import BaseWWTask
    if getattr(BaseWWTask, '_cloud_loot', False):
        return
    original_find = BaseWWTask.find_f_with_claim_text
    original_pick = BaseWWTask.pick_f
    original_treasure = BaseWWTask.find_treasure_icon

    def treasure(self):
        if not self.is_browser():
            return original_treasure(self)
        # A nearby Claim Rewards interaction is also a positive reward target.
        # The material gate still independently checks timer/enemies/progress.
        prompt = claim_prompt(self)
        if prompt:
            return prompt
        # Cloud compression weakens small icons; use the requested 0.70
        # threshold without depending on a disappearing objective label.
        # Recognition supplies evidence, not permission to bypass the gate.
        return self.find_one('treasure_icon',
            box=self.box_of_screen(.03,.1,.97,.81,hcenter=True,vcenter=True),
            threshold=.70,target_height=720)

    def find(self):
        result = original_find(self)
        if result or not self.is_browser():
            return result
        return claim_prompt(self)

    def pick(self, handle_claim=True):
        if not self.is_browser() or handle_claim:
            return original_pick(self, handle_claim)
        # Native walk may already have reached the reward dialog.
        if self.has_claim_stamina():
            return True
        result = original_pick(self, handle_claim=False)
        if not result:
            if not claim_prompt(self):
                return result
            self.send_key('f', after_sleep=1)
        self.wait_until(self.has_claim_stamina, time_out=5, raise_if_not_found=True)
        return True

    BaseWWTask.find_f_with_claim_text = find
    BaseWWTask.pick_f = pick
    BaseWWTask.find_treasure_icon = treasure
    BaseWWTask._cloud_loot = True
