"""Explicit final-nest failure skip; never record incomplete combat as victory."""
import json
from datetime import datetime,timezone
from pathlib import Path
from cloud_autorun_state import day_key
from cloud_nest_state import OPTIONAL_PICKUP_TARGET,TERMINAL_PHASES

POLICY='skip_after_three_recoveries'
SKIPPED='SKIPPED_ALLOWED_FAILURE'
OTHER_NESTS={'梦枢天罗残象聚落':48,'落渊南丘残象聚落':41,'盲望之塌残象聚落':48,'复生丘原残象聚落':48}
EXHAUSTED={'Same-nest objective recovery retry limit reached','Same-nest revival retry limit reached'}

def validate_final_skip(receipt):
    catalog=receipt.get('catalog',{})
    if (receipt.get('status')!=SKIPPED or receipt.get('policy')!=POLICY
            or receipt.get('skipped_targets')!=[OPTIONAL_PICKUP_TARGET]
            or receipt.get('source')!='owned_failure_with_user_authorized_final_skip'
            or receipt.get('recovery_attempts')!=3 or receipt.get('failure_reason') not in EXHAUSTED
            or receipt.get('catalog_complete') is not False or receipt.get('stamina_claims')!=0
            or set(catalog)!=set(OTHER_NESTS)|{OPTIONAL_PICKUP_TARGET}
            or any(catalog[n]!=[total,total] for n,total in OTHER_NESTS.items())):
        raise RuntimeError('Final-nest skip receipt is incomplete or outside its authorization')
    count=catalog[OPTIONAL_PICKUP_TARGET]
    if len(count)!=2 or count[1]!=24 or not 0<=count[0]<=24:
        raise RuntimeError('Final-nest skipped count is invalid')
    return receipt

def collect_final_skip(day,owner,out,state,config):
    if config.get('final_nest_failure_policy')!=POLICY:return None
    out,state=Path(out),Path(state)
    events=[json.loads(x) for x in (out/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    failed=[e for e in events if e.get('event')=='batch_failed']
    if len(failed)!=1 or failed[0].get('error') not in EXHAUSTED:return None
    last=failed[0]
    selected=[e for e in events if e.get('event')=='selected']
    if len(selected)<3 or any(e.get('name')!=OPTIONAL_PICKUP_TARGET for e in selected[-3:]):return None
    native=json.loads((state/'nightmare-result.json').read_text(encoding='utf-8'))
    if native.get('status')!='FAILED' or native.get('run_id')!=owner or native.get('retry_allowed') is not True:
        raise RuntimeError('Final-nest failure is unowned or unsafe to continue')
    if day_key(datetime.fromtimestamp(last['at'],timezone.utc))!=day or day_key()!=day:
        raise RuntimeError('Final-nest skip crossed the game-day boundary')
    from cloud_accounts import account_paths
    from cloud_restart_resume import assert_controls
    assert_controls(state,[account_paths(state,a).state for a in ('a','b','c')])
    registry=json.loads((state/'accounts/registry.json').read_text(encoding='utf-8'))
    account_hash=next(a['expected_uid_hash'] for a in registry['accounts'] if a['id']=='a')
    checkpoints=[json.loads(p.read_text(encoding='utf-8')) for p in state.glob('nest-state-*.json')]
    checkpoints={r['target']:r for r in checkpoints if r.get('day')==day and r.get('account')==account_hash}
    if set(checkpoints)!=set(OTHER_NESTS)|{OPTIONAL_PICKUP_TARGET}:
        raise RuntimeError('Other nest checkpoints are missing; final skip cannot close the batch')
    for name,total in OTHER_NESTS.items():
        r=checkpoints[name]
        if r.get('phase') not in TERMINAL_PHASES or r.get('verified_count')!=[total,total]:
            raise RuntimeError('Another nest is unfinished; final skip cannot close the batch')
    final=checkpoints[OPTIONAL_PICKUP_TARGET]
    if final.get('total')!=24 or final.get('phase') not in ('IN_PROGRESS','CLEARED_PENDING_PICKUP'):
        raise RuntimeError('Final-nest skip checkpoint phase is not an unfinished attempt')
    image=out/last['image']
    if not image.is_file():raise RuntimeError('Final-nest failure image is missing')
    import hashlib
    receipt=dict(status=SKIPPED,source='owned_failure_with_user_authorized_final_skip',policy=POLICY,
        run_id=owner,game_day=day,completed_at=max(native['at'],last['at']),
        evidence_directory=str(out),failure_image=str(image),failure_image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
        failure_reason=last['error'],recovery_attempts=3,skipped_targets=[OPTIONAL_PICKUP_TARGET],
        catalog={n:checkpoints[n]['verified_count'] for n in OTHER_NESTS},catalog_complete=False,
        stamina_claims=0,absorption_claimed=False,native_failure_preserved=True,
        last_verified_count=final['book_count'])
    receipt['catalog'][OPTIONAL_PICKUP_TARGET]=final['book_count']
    return validate_final_skip(receipt)
