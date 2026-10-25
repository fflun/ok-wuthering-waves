"""Restart reconciliation; caller must hold runner.lock before calling.

Only runs interrupted by a real system boot are eligible. Ordinary failures,
manual stops and uncertain spending never become fresh attempts here.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from cloud_autorun_state import day_key, week_key, write_json


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else {}


def system_snapshot(root):
    import psutil
    root=Path(root).resolve()
    workspace=str(root.parent.parent).lower()
    active=[]
    for process in psutil.process_iter(['pid','name','cmdline','create_time']):
        if process.pid==os.getpid():continue
        try:
            info=process.info
            if not info['name'] or not info['name'].lower().startswith('python'):continue
            if info['cmdline'] is None:raise RuntimeError('Cannot verify an existing Python process')
            command=' '.join(info['cmdline']).lower()
            if workspace in command and any(x in command for x in
                    ('main_cloud','run_a_','continue_a_','retry_a_','cloud_full')):
                active.append(dict(pid=info['pid'],created_at=info['create_time']))
        except psutil.NoSuchProcess:continue
        except psutil.AccessDenied:raise RuntimeError('Cannot verify an existing automation process')
    return dict(boot_at=psutil.boot_time(),active=active)


def timestamp(value):
    return datetime.fromisoformat(value).timestamp() if isinstance(value,str) else float(value)


def assert_controls(background,states):
    for state in states:
        if any((state/name).exists() for name in ('stop-request','pause-request')):
            raise RuntimeError('local_stop_request; restart cannot override it')
        pending=background.parent/'claim-pending.json' if state==background else state/'claim-pending.json'
        if pending.exists():raise RuntimeError('pending_claim_needs_review')
        # Food use is journaled before F; missing food is an optional skip,
        # but an interrupted actual use must not be issued a second time.
        for path in [state/'food-receipt.json',*state.glob('boss-food/*.json'),
                     *state.glob('boss-food-reentry/*.json')]:
            record=read(path)
            if record.get('pending'):raise RuntimeError('pending_food_use_needs_review')


def validate_checkpoint(state,account_hash,day,stage):
    if stage=='daily':return dict(mode='live_daily_activity_stamina_mail_radio_recheck')
    if stage in ('boss','garden'):return dict(mode='live_weekly_quota_recheck')
    if stage=='boss_echo':
        path=state/f'boss-echo-progress-{day}.json'
        record=read(path)
        if not record:return dict(mode='live_identity_before_first_boss',completed=0)
        if (record.get('account')!=account_hash or record.get('game_day')!=day
                or record.get('target')!='weekly-list-1-level-80' or record.get('goal')!=20):
            raise RuntimeError('Restart boss checkpoint account/day/target mismatch')
        rounds=record.get('rounds',[]);pending=record.get('pending')
        if (len(rounds)>20 or [r.get('round') for r in rounds]!=list(range(1,len(rounds)+1))
                or any(r.get('pickup_search_completed') is not True for r in rounds)
                or pending and pending.get('round')!=len(rounds)+1):
            raise RuntimeError('Restart boss checkpoint sequence is invalid')
        for r in rounds+([pending] if pending else []):
            for field in ('victory_image',) if r is pending else ('victory_image','pickup_image'):
                if not r.get(field) or not Path(r[field]).is_file():
                    raise RuntimeError('Restart boss checkpoint evidence missing')
        return dict(mode='pending_pickup_first' if pending else 'remaining_boss_rounds',completed=len(rounds))
    if stage!='nest_echo':raise RuntimeError('Unknown restart stage')
    records=[read(p) for p in state.glob('nest-state-*.json')]
    records=[r for r in records if r.get('day')==day and r.get('account')==account_hash]
    pending=[]
    for r in records:
        total=r.get('total');count=r.get('book_count',[])
        if (total not in (24,36,41,48) or len(count)!=2 or count[1]!=total
                or not 0<=count[0]<=total or not r.get('target','').endswith('残象聚落')
                or r.get('phase') not in ('PICKED_UP','IN_PROGRESS','CLEARED_PENDING_PICKUP','SEARCHED_NO_ECHO','PICKUP_UNCONFIRMED_ALLOWED')):
            raise RuntimeError('Restart nest checkpoint invalid')
        if r['phase'] in ('IN_PROGRESS','CLEARED_PENDING_PICKUP'):pending.append(r)
        if r['phase']!='IN_PROGRESS' and r.get('verified_count')!=[total,total]:
            raise RuntimeError('Restart nest completion evidence invalid')
        if r['phase']=='SEARCHED_NO_ECHO':
            import hashlib
            proof=r.get('pickup_search',{});image=Path(proof.get('image',''))
            if (proof.get('target')!=r['target'] or proof.get('count')!=[total,total]
                    or proof.get('absorb_sent') is not False or proof.get('stable_target_seen') is not False
                    or proof.get('native_circle_completed') is not True or not image.is_file()
                    or hashlib.sha256(image.read_bytes()).hexdigest()!=proof.get('image_sha256')):
                raise RuntimeError('Restart empty-search evidence invalid')
        if r['phase']=='PICKUP_UNCONFIRMED_ALLOWED':
            from cloud_nest_state import OPTIONAL_PICKUP_TARGET
            import hashlib
            proof=r.get('pickup_search',{});image=Path(proof.get('image',''))
            if (r['target']!=OPTIONAL_PICKUP_TARGET or total!=24 or r.get('absorbed') is not False
                    or proof.get('target')!=r['target'] or proof.get('count')!=[24,24]
                    or proof.get('bounded_search_completed') is not True
                    or proof.get('user_policy')!='final_nest_ignore_unconfirmed_absorption'
                    or not isinstance(proof.get('absorb_sent'),bool) or not image.is_file()
                    or hashlib.sha256(image.read_bytes()).hexdigest()!=proof.get('image_sha256')):
                raise RuntimeError('Restart final-nest continuation evidence invalid')
    if len(pending)>1:raise RuntimeError('Multiple pending nest checkpoints')
    return dict(mode='same_named_nest_live_recheck',picked=sum(r['phase']=='PICKED_UP' for r in records),
                pending_target=pending[0]['target'] if pending else None,
                pending_phase=pending[0]['phase'] if pending else None)


def completed_receipt(state,stage,period,item,root):
    owner=item.get('run_id')
    if not owner:return None
    if stage in ('boss_echo','nest_echo'):
        from cloud_full_chain import collect_echo_receipt
        folder=Path(root).parent.parent/'outputs'/f'full-{period}-{stage}-{owner}'
        events=folder/'events.jsonl'
        if not events.exists():return None
        if stage=='nest_echo':
            from cloud_final_nest_policy import collect_final_skip
            skipped=collect_final_skip(period,owner,folder,state,read(state/'autorun-config.json'))
            if skipped:return skipped
        if not any(json.loads(line).get('event')=='batch_succeeded' for line in events.read_text(encoding='utf-8').splitlines()):return None
        return collect_echo_receipt(stage,period,owner,folder,state)
    path=state/({'daily':'daily','boss':'echo','garden':'garden-state'}[stage]+'.json' if stage=='garden'
                else {'daily':'daily','boss':'echo'}[stage]+'-result.json')
    receipt=read(path)
    if receipt.get('status')!='SUCCEEDED' or receipt.get('run_id')!=owner:return None
    started=timestamp(item['started_at'])
    if receipt.get('completed_at',0)<started:raise RuntimeError('Restart completion receipt is stale')
    if stage=='daily':
        from cloud_daily_closure import complete
        v=receipt.get('daily_verification',{})
        if (v.get('game_day')!=period or v.get('complete') is not True or v.get('activity',0)<100
                or v.get('verified_rewards')!=5 or v.get('all_daily_complete') is not True
                or v.get('verified_at',0)<started or not complete(v.get('closure'),period)):
            raise RuntimeError('Restart daily completion evidence incomplete')
    return dict(receipt,game_week=receipt.get('game_week') or period)


def reconcile(root,background,config,*,snapshot=None,now=None):
    """Prepare only stopped pre-boot RUNNING entries; never launch game inputs."""
    from cloud_accounts import account_paths
    from cloud_autorun_state import DailyLedger
    from cloud_full_chain import FullLedger
    from cloud_weekly_state import WeeklyLedger
    root,background=Path(root),Path(background)
    snapshot=snapshot or system_snapshot(root)
    if snapshot['active']:raise RuntimeError('Existing automation child is still active; no second runner')
    now=now or datetime.now(timezone.utc);day=day_key(now);week=week_key(now)
    registry=read(background/'accounts/registry.json')
    identities={r['id']:r.get('expected_uid_hash') for r in registry.get('accounts',[])}
    from cloud_small_account_chain import small_account_order
    slots=['a']+small_account_order(config)
    states=[account_paths(background,a).state for a in slots]
    assert_controls(background,states)
    plan=[]
    for account,state in zip(slots,states):
        for kind,filename,ledger in [('daily','daily-ledger.json',DailyLedger(state/'daily-ledger.json')),
                                     ('full','full-ledger.json',FullLedger(state/'full-ledger.json')),
                                     ('weekly','weekly-ledger.json',WeeklyLedger(state/'weekly-ledger.json'))]:
            if account!='a' and kind!='daily':continue
            records=ledger.read()
            for period,group in records.items():
                entries=[('daily',group)] if kind=='daily' else list(group.items())
                for stage,item in entries:
                    if item.get('status')!='RUNNING':continue
                    started=timestamp(item['started_at'])
                    if started>=snapshot['boot_at']:raise RuntimeError('Interruption is not a reboot; needs review')
                    if period!=(week if kind=='weekly' else day):
                        raise RuntimeError('Interrupted checkpoint crossed 04:00 or weekly refresh; needs review')
                    if not identities.get(account):raise RuntimeError('Restart account identity is unbound')
                    proof=validate_checkpoint(state,identities[account],day,stage)
                    if kind=='weekly' and stage=='boss':
                        claims=item.get('claims',[])
                        if (len(claims)>3 or len({c.get('claim_id') for c in claims})!=len(claims)
                                or any(c.get('status')!='CLAIM_VERIFIED' or c.get('cost')!=60
                                       or not c.get('claim_id') for c in claims)):
                            raise RuntimeError('Restart weekly claim checkpoint invalid')
                        proof['verified_claims']=len(claims)
                    receipt=completed_receipt(state,stage,period,item,root)
                    plan.append((ledger,kind,period,stage,item,proof,receipt,account))
    # All controls, periods and checkpoints are checked before the first write.
    audit=[]
    for ledger,kind,period,stage,item,proof,receipt,account in plan:
        if receipt:
            if kind=='daily':ledger.finish(period,'SUCCEEDED','Owned completion reconciled after reboot',receipt=receipt)
            else:ledger.finish(period,stage,item['run_id'],receipt)
            action='owned_completion_restored'
        else:
            records=ledger.read();entry=records[period] if kind=='daily' else records[period][stage]
            history_key='attempts' if kind=='daily' else 'history'
            entry.setdefault(history_key,[]).append({k:v for k,v in entry.items() if k!=history_key})
            entry.update(status='READY',restart_recovery=dict(boot_at=snapshot['boot_at'],verified_at=now.timestamp(),
                checkpoint=proof,prior_run_id=item.get('run_id')))
            write_json(ledger.path,records)
            action='checkpoint_ready_for_live_recheck'
        audit.append(dict(account=account,stage=stage,period=period,action=action,checkpoint=proof))
    write_json(background/'restart-check.json',dict(status='VERIFIED',boot_at=snapshot['boot_at'],
        verified_at=now.timestamp(),actions=audit,pid=os.getpid()))
    return audit
