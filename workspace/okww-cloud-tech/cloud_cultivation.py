"""Navigate the account's cultivation recommendation, never the domain index."""
import re
import os,json,time
from pathlib import Path

def first_material_button(boxes):
    rows=[b for b in boxes if re.fullmatch('武器[与與]技能素材',b.name.strip()) and b.x>450]
    if not rows:raise RuntimeError('Cultivation weapon/skill material row unreadable')
    row=min(rows,key=lambda b:b.y)
    buttons=[b for b in boxes if b.name.strip()=='前往' and b.x>1000
             and abs((b.y+b.height/2)-(row.y+row.height/2))<28]
    if len(buttons)!=1:raise RuntimeError('Cultivation first material button ambiguous')
    return buttons[0]

def open_recommended(task):
    task.openF2Book('gray_book_boss')
    targets=task.ocr(.09,.10,.35,.23,match=re.compile('^培养目标$'))
    if len(targets)!=1:raise RuntimeError('Cultivation target entry unreadable')
    task.click(targets[0],after_sleep=1)
    task.next_frame()
    if not task.ocr(.36,.10,.75,.21,match=re.compile('^所需材料$')):
        raise RuntimeError('Cultivation required-materials page not verified')
    task.click(first_material_button(task.ocr()),after_sleep=2)
    task.next_frame()
    if task.ocr(.36,.10,.75,.21,match=re.compile('^所需材料$')):
        # First click can select the row; one bounded second activation.
        task.click(first_material_button(task.ocr()),after_sleep=5)

def enter_recommended(task):
    import cv2
    open_recommended(task)
    task.next_frame()
    levels=task.ocr(.05,.10,.28,.65,match=re.compile(r'^等级\d+$'))
    selected=[]
    for box in levels:
        y=int(box.y+box.height/2)
        if task.frame[y-6:y+6,260:280].mean()>150:
            selected.append(int(re.search(r'\d+',box.name).group()))
    buttons=task.ocr(.78,.86,.98,.97,match=re.compile('^单人挑战$'))
    if len(selected)!=1 or len(buttons)!=1:
        raise RuntimeError('Recommended domain selected level or solo entry unreadable')
    out=Path(os.environ['OKWW_DAILY_OUTPUT'])
    cv2.imwrite(str(out/'recommended-domain.png'),task.frame)
    (out/'recommended-domain.json').write_text(json.dumps({'selected_level':selected[0],
        'policy':'game_default_highest_accessible','time':time.time()},ensure_ascii=False),encoding='utf-8')
    task.click(buttons[0],after_sleep=1)
    task.click_team_challenge()
    task.wait_in_team_and_world(time_out=task.teleport_timeout)

def install_start_recovery(task):
    native=task.walk_until_f
    def walk(*args,**kwargs):
        from ok import CannotFindException
        try:return native(*args,**kwargs)
        except CannotFindException:
            task.next_frame()
            # Only recover a verified, not-yet-started challenge. Never search
            # during combat or repurpose a reward/exit interaction.
            if not task.ocr(.01,.20,.28,.32,match=re.compile('开启挑战')):raise
            if task.ocr(.44,.10,.57,.17,match=re.compile(r'\d+[:：]\d+')):raise
            task.log_info('CLOUD_CULTIVATION start interaction missing: bounded forward search')
            found = task.send_key_and_wait_f('w',False,8,target_text=re.compile('开启挑战'))
            if found:return found
            task.next_frame()
            # Recheck a fresh unstarted scene before the one reverse search.
            if not task.ocr(.01,.20,.28,.32,match=re.compile('开启挑战')):raise
            if task.ocr(.44,.10,.57,.17,match=re.compile(r'\d+[:：]\d+')):raise
            task.log_info('CLOUD_CULTIVATION start interaction missing: bounded reverse search')
            return task.send_key_and_wait_f('s',True,8,target_text=re.compile('开启挑战'))
    task.walk_until_f=walk
