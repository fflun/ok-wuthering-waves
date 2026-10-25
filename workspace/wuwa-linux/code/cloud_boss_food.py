"""Renew food only at new20-round target boundaries, never during a batch."""
import hashlib,json,time
from pathlib import Path
from cloud_food import FoodReceipt,FoodUnconfirmed,prepare
from cloud_autorun_state import day_key,write_json


def leave_instance_for_food(task):
    """Reach the world for food without selecting a potentially unopened healing point."""
    import re
    from cloud_revive import dungeon_exit_context
    task.executor.interaction.release_all()
    task.ensure_main(time_out=30)
    if not task.in_world():
        task.send_key('esc',after_sleep=1)
        def exit_button():
            if not dungeon_exit_context(task.ocr(.18,.25,.86,.82)):return None
            boxes=task.ocr(.50,.50,.86,.80,match=re.compile(r'^(确认|確認|退出副本|退出挑战|退出挑戰|离开|離開)$'))
            return boxes[0] if len(boxes)==1 else None
        if task.wait_until(exit_button,time_out=5,raise_if_not_found=False) is None:
            raise FoodUnconfirmed('Reentry food dungeon exit not identified')
        task.next_frame();button=exit_button()
        if button is None:raise FoodUnconfirmed('Reentry food exit changed before click')
        task.click_box(button,after_sleep=1)
        if not task.wait_until(task.in_world,time_out=120,raise_if_not_found=False):
            raise FoodUnconfirmed('Reentry food open world not verified')
    task.reset_to_false(reason='open world verified before authorized reentry food')


def prepare_reentry(task,output,account,target,state,request_path,completed,leave_instance):
    """An explicitly authorized extra use after reconnect; distinct from transition food."""
    request_path=Path(request_path)
    if not request_path.exists():return False
    request=json.loads(request_path.read_text(encoding='utf8'))
    if request.get('target')!=target:return False
    if (request.get('game_day')!=day_key() or request.get('account')!='a'
            or request.get('item')!='糖醋里脊' or request.get('quantity')!=1
            or not reentry_id_valid(request.get('id'))):
        raise FoodUnconfirmed('Reentry food authorization scope invalid')
    path=Path(state)/'boss-food-reentry'/(request['id']+'.json')
    session='reentry:'+request['id']
    receipt=FoodReceipt(path,account,session);receipt.check()
    if len(receipt.data['uses'])>1:raise FoodUnconfirmed('Reentry food used more than once')
    if request.get('status')=='SKIPPED':
        if receipt.data['uses'] or not any(s.get('session')==session for s in receipt.data.get('skipped_sessions',[])):
            raise FoodUnconfirmed('Reentry food skip lacks a no-use receipt')
        return False
    if request.get('status')=='DONE':
        if len(receipt.data['uses'])!=1:raise FoodUnconfirmed('Reentry food completion has no receipt')
        return False
    if request.get('status')!='READY' or request.get('completed_before')!=completed:
        raise FoodUnconfirmed('Reentry food request conflicts with saved progress')
    if not receipt.data['uses']:
        leave_instance()
        used=prepare(task,output,receipt_path=path,session=session)
        receipt=FoodReceipt(path,account,session);receipt.check()
        if used is False:
            if receipt.data['uses'] or not any(s.get('session')==session for s in receipt.data.get('skipped_sessions',[])):
                raise FoodUnconfirmed('Reentry food skip lacks a no-use receipt')
            request.update(status='SKIPPED',receipt=str(path),skipped_at=time.time(),used=False)
            write_json(request_path,request)
            return False
    if len(receipt.data['uses'])!=1:raise FoodUnconfirmed('Reentry food not verified')
    request.update(status='DONE',receipt=str(path),used_at=receipt.data['uses'][0]['used_at'])
    write_json(request_path,request)
    return True


def reentry_id_valid(value):
    import re
    return isinstance(value,str) and bool(re.fullmatch(r'[a-z0-9-]{1,80}',value))


def transition_receipt(state,account,target):
    scope=hashlib.sha256((account+'\0'+target).encode()).hexdigest()
    return Path(state)/'boss-food'/f'{scope}.json'


def latest_boss_food(state,account):
    scope=FoodReceipt(Path(state)/'unused-scope.json',account,'scope').scope
    uses=[]
    for directory in ('boss-food','boss-food-reentry'):
        for path in (Path(state)/directory).glob('*.json'):
            data=json.loads(path.read_text(encoding='utf8'))
            if any(data.get(k)!=v for k,v in scope.items()):continue
            if data.get('pending'):raise FoodUnconfirmed('Account food use unresolved before new target')
            uses.extend(data.get('uses',[]))
    return max(uses,key=lambda use:use['used_at']) if uses else None


def prepare_transition(task,output,account,target,state,*,completed=0,renew_after_seconds=1500):
    if renew_after_seconds not in (1500,1800):raise FoodUnconfirmed('Boss food renewal threshold invalid')
    path=transition_receipt(state,account,target)
    receipt=FoodReceipt(path,account,target)
    receipt.check()  # pending or a refresh must never trigger another use
    if len(receipt.data['uses'])>1:raise FoodUnconfirmed('More than one food use for this boss')
    if receipt.data['uses']:
        result='already_verified'
    elif receipt.data.get('boundary_decision'):
        result='boundary_already_checked'
    elif completed>0:
        # A resume of an interrupted target is still the same20-round cycle.
        result='mid_batch_resume_no_food'
    else:
        latest=latest_boss_food(state,account)
        now=time.time()
        if latest and latest['used_at']>now:raise FoodUnconfirmed('Food receipt timestamp is in the future')
        if latest and now-latest['used_at']<renew_after_seconds:
            result='effect_retained_at_boundary'
            receipt.data['boundary_decision']=dict(result=result,at=now,
                previous_used_at=latest['used_at'],renew_after_seconds=renew_after_seconds)
            write_json(path,receipt.data)
        else:
            used=prepare(task,output,receipt_path=path,session=target)
            receipt=FoodReceipt(path,account,target);receipt.check()
            if used is False:
                if receipt.data['uses']:raise FoodUnconfirmed('Skipped food conflicts with actual use')
                result='food_unavailable_skipped'
                receipt.data['boundary_decision']=dict(result=result,at=time.time(),
                    renew_after_seconds=renew_after_seconds)
                write_json(path,receipt.data)
            else:
                if len(receipt.data['uses'])!=1:raise FoodUnconfirmed('Boss food receipt not verified')
                result='used'
    with (Path(output)/'food-events.jsonl').open('a',encoding='utf8') as stream:
        stream.write(json.dumps(dict(at=time.time(),event='boss_food_ready',target=target,
            result=result,receipt=str(path)),ensure_ascii=False)+'\n')
    return True
