"""Explicit no-charge weekly replays: verify exhausted quota, then exit once."""
import hashlib,json,os,re,time
from pathlib import Path

QUOTA=re.compile(r'^收取物[资資]次数已达到上限[，,]?是否退出副本[？?]?$')
INTERACTION=re.compile(r'^(领取奖励|領取獎勵|离开副本|離開副本)$')

def enabled():
    return os.environ.get('OKWW_WEEKLY_REPLAY_STAGE') in ('weekly_probe_1','weekly_probe_2','weekly_probe_3')

def quota_text(text):
    return bool(QUOTA.fullmatch(re.sub(r'\s+','',text)))

def quota_snapshot(task):
    body=''.join(b.name for b in task.ocr(.20,.35,.80,.54))
    if not quota_text(body):return None
    left=task.ocr(.20,.55,.49,.72,match=re.compile('^退出副本$'))
    right=task.ocr(.51,.55,.80,.72,match=re.compile('^重新挑战$'))
    if len(left)!=1 or len(right)!=1:raise RuntimeError('Weekly quota exit controls are not unique')
    return {'text':re.sub(r'\s+','',body),'exit':left[0],'restart':right[0]}

def same(a,b):
    return bool(a and b and a['text']==b['text'] and all(abs(getattr(a[k],axis)-getattr(b[k],axis))<=12 for k in ('exit','restart') for axis in ('x','y')))

def save_frame(task,path):
    import cv2
    if not cv2.imwrite(str(path),task.frame):raise RuntimeError('Weekly replay evidence write failed')
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def controls_clear():
    from cloud_restart_resume import assert_controls
    state=Path(__file__).resolve().parent.parent/'okww-cloud-session/background'
    assert_controls(state,[state])

def open_exhausted_endpoint(task):
    if quota_snapshot(task):return
    if task.has_health_bar() or not task.combat_end_condition():
        raise RuntimeError('Weekly replay has no positive completed objective')
    if not task.find_f_with_text(target_text=INTERACTION):
        raise RuntimeError('Weekly replay reward/exit interaction not positively identified')
    task.sleep(.3);task.next_frame()
    if task.has_health_bar() or not task.combat_end_condition() or not task.find_f_with_text(target_text=INTERACTION):
        raise RuntimeError('Weekly replay interaction changed before opening')
    task.send_key('f',after_sleep=1)
    task.wait_until(lambda:quota_snapshot(task) is not None,time_out=5,raise_if_not_found=True)

def leave_endpoint(task,output,prefix):
    controls_clear();task.next_frame();first=quota_snapshot(task)
    if not first:raise RuntimeError('No exhausted weekly quota dialog; refusing exit guess')
    before=save_frame(task,output/(prefix+'-quota-first.png'))
    task.sleep(.3);task.next_frame();second=quota_snapshot(task)
    if not same(first,second):raise RuntimeError('Weekly quota dialog changed before exit')
    after=save_frame(task,output/(prefix+'-quota-second.png'))
    controls_clear()
    # Explicit left Exit Dungeon text; never the right Restart or any claim confirmation.
    task.click_box(second['exit'],after_sleep=2)
    task.wait_until(lambda:bool(task.in_world()) and not task.in_realm(),time_out=120,raise_if_not_found=True)
    task.sleep(.3);task.next_frame()
    if not task.in_world() or task.in_realm():raise RuntimeError('Weekly replay exit did not persist in world')
    controls_clear();world=save_frame(task,output/(prefix+'-world.png'))
    return {'endpoint':'WEEKLY_QUOTA_EXHAUSTED','observed_text':second['text'],'quota_images':[before,after],'world_image':world,'exit_verified':True,'reward_claimed':False}

def verified_predecessor(path,day,stage):
    index=json.loads(Path(path).read_text()).get(day,{}).get(stage)
    if not index or index.get('status')!='VERIFIED':return None
    proof=Path(index['receipt_path'])
    if not proof.is_file() or hashlib.sha256(proof.read_bytes()).hexdigest()!=index['sha256']:
        raise RuntimeError('Weekly predecessor evidence changed')
    record=json.loads(proof.read_text())
    if record.get('run_id')!=index['run_id'] or record.get('game_day')!=day or record.get('reward_claimed') is not False:
        raise RuntimeError('Weekly predecessor scope mismatch')
    return record

def prepare_entry(task,output):
    if not enabled():return
    stage=os.environ['OKWW_WEEKLY_REPLAY_STAGE'];number=int(stage[-1])
    if number==1:return
    from cloud_autorun_state import day_key
    previous=verified_predecessor(Path('/opt/cloudgames/full-alignment-20261023/verified-replays.json'),day_key(),'weekly_probe_'+str(number-1))
    if previous is None:raise RuntimeError('Weekly replay predecessor is not verified')
    task.next_frame()
    if task.in_world() and not task.in_realm():return
    if not quota_snapshot(task):open_exhausted_endpoint(task)
    record=leave_endpoint(task,output,'prior-replay-exit')
    record.update(previous_owner=previous['run_id'],at=time.time(),current_replay_not_counted=True)
    (output/'prior-replay-exit.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    task.log_info('CLOUD_WEEKLY_REPLAY prior verified realm exited without claim; new battle still required')

def finish_probe(task,output):
    if not enabled():raise RuntimeError('Weekly replay endpoint used outside explicit replay scope')
    if not getattr(task,'_cloud_weekly_victory',False):raise RuntimeError('Fresh weekly victory is not confirmed')
    open_exhausted_endpoint(task)
    record=leave_endpoint(task,output,'weekly-replay')
    # Preserve the historical filenames but bind them to actual verified endpoint evidence.
    import shutil
    shutil.copy2(record['quota_images'][1]['path'],output/'weekly-reward-probe.png')
    (output/'weekly-reward-probe.json').write_text(json.dumps([{'text':record['observed_text']},{'text':'退出副本'},{'text':'重新挑战'}],ensure_ascii=False,indent=2))
    from cloud_autorun_state import day_key
    record.update(status='REPLAY_ENDPOINT_VERIFIED',game_day=day_key(),run_id=os.environ['OKWW_WEEKLY_RUN_ID'],at=time.time())
    (output/'weekly-probe-complete.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    task.log_info('CLOUD_WEEKLY_REPLAY quota exhausted verified twice; returned to world; no claim')
