"""Bounded Flash recovery for an exit prompt obscuring an unclaimed reward."""
import json
import os
import re
import time
import urllib.error
import urllib.request

EXIT = re.compile(r'离开副本|離開副本|Leave Domain|Exit Domain', re.I)
ACTIONS = {'step_back': 's', 'step_left': 'a', 'step_right': 'd', 'observe': None, 'stop': None}
MAX_ATTEMPTS = 2  # Shared by combat-exit and reward-walk checks on this task instance.


def exit_visible(task):
    return bool(task.ocr(.64,.36,.94,.65,match=EXIT))


def eligible(evidence, exit_prompt):
    return bool(exit_prompt and evidence.valid and evidence.team and not any((
        evidence.timer, evidence.enemies, evidence.unfinished, evidence.recovery, evidence.reward)))


def choose_action(context, request=None):
    key=os.environ.get('DEEPSEEK_API_KEY')
    if not key:raise RuntimeError('Reward recovery unavailable: missing DEEPSEEK_API_KEY')
    payload=dict(model='deepseek-flash', max_tokens=256, response_format={'type':'json_object'},
        messages=[dict(role='system',content=(
            'You recover a game reward navigation stall. Exit Domain is visible and may cover the reward marker. '
            'There is currently no timer, enemy, unfinished objective or revival dialog. '
            'Choose one short action to uncover the reward. Prefer step_back initially; use observation or a '
            'different lateral step if the first action did not help. Return JSON only {"action": name}. '
            'Allowed names: step_back, step_left, step_right, observe, stop. '
            'Movement is 0.18 seconds. Never press F, exit, attack, purchase, claim, or declare completion. '
            'The caller will freshly verify every action and completion.')),
            dict(role='user',content=json.dumps(context))])
    req=urllib.request.Request('https://api.deepseek.com/chat/completions',data=json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with (request or urllib.request.urlopen)(req,timeout=15) as response:data=json.load(response)
        answer=json.loads(data['choices'][0]['message']['content'])
        if type(answer) is not dict or set(answer)!={'action'} or type(answer['action']) is not str or answer['action'] not in ACTIONS:
            raise ValueError('unsupported action')
        return answer['action']
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Reward recovery API HTTP {exc.code}') from None
    except Exception as exc:
        raise RuntimeError(f'Reward recovery API rejected ({type(exc).__name__})') from None


def recover(task):
    from cloud_material_combat import read_evidence
    if os.environ.get('OKWW_REWARD_DEEPSEEK','1')!='1' or not getattr(task,'is_browser',lambda:False)():
        return False
    attempts=getattr(task,'_cloud_reward_recovery_attempts',0)
    if attempts>=MAX_ATTEMPTS:return False
    interaction=task.executor.interaction
    interaction.release_all()
    try:
        # Two fresh observations prevent a single missed timer/health bar
        # from authorizing movement while an actual battle is still visible.
        for _ in range(2):
            task.next_frame()
            evidence,_=read_evidence(task)
            if not eligible(evidence,exit_visible(task)):return False
            time.sleep(.15)
        task._cloud_reward_recovery_attempts=attempts+1
        history=getattr(task,'_cloud_reward_recovery_history',[])
        task.log_info(f'CLOUD_REWARD_RECOVERY request={attempts+1}/{MAX_ATTEMPTS} model=deepseek-flash')
        action=choose_action(dict(stage='exit_prompt_occludes_reward',attempt=attempts+1,previous_actions=history))
        if action=='stop':return False
        # A model response is not permission to act on an old frame.
        task.next_frame()
        evidence,_=read_evidence(task)
        if not eligible(evidence,exit_visible(task)):
            task.log_info('CLOUD_REWARD_RECOVERY scene changed; skip action and recheck')
            return True
        task._cloud_reward_recovery_history=history+[action]
        task.log_info(f'CLOUD_REWARD_RECOVERY action={action}; completion remains unverified')
        key=ACTIONS[action]
        if key:
            # Direct transport avoids recursive combat checks inside task.sleep.
            interaction.send_key_down(key)
            try:time.sleep(.18)
            finally:interaction.send_key_up(key)
        time.sleep(.25)
        return True
    finally:
        interaction.release_all()
