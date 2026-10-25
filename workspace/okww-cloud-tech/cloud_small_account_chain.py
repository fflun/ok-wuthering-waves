"""B/C daily tail after A full flow; caller owns the shared runner lock."""
from cloud_autorun_state import day_key,week_key
from cloud_accounts import account_paths
from cloud_daily_retry import run_daily


def small_account_order(config):
    order=config.get('small_accounts_after_full',[])
    if order not in ([],['b','c'],['c','b']):
        raise ValueError('Small account order must contain B and C once each')
    return list(order)


def run_tail(result,state,execute,check,notify_retry=None,notify_recovered=None,order=('c','b')):
    order=small_account_order({'small_accounts_after_full':list(order)})
    if result.get('mode')!='full' or result.get('status') not in ('SUCCEEDED','SKIPPED','SUCCEEDED_WITH_SKIPS'):
        raise RuntimeError('A full flow must complete before B/C')
    if result.get('status')=='SUCCEEDED_WITH_SKIPS':
        from cloud_final_nest_policy import validate_final_skip
        if len(result.get('allowed_skips',[]))!=1:raise RuntimeError('Allowed final-nest skip proof is missing')
        validate_final_skip(result['allowed_skips'][0])
    day=result['day'];done=[]
    def boundary():
        if day_key()!=day:raise RuntimeError('Game day refreshed; stop B/C chain')
    for account in order:
        boundary();check(account)
        ledger=account_paths(state,account).ledgers()['daily']
        if ledger.read().get(day,{}).get('status')=='SUCCEEDED':continue
        run_daily(ledger,day,lambda owner:execute(account,owner),boundary,retries=1,
            retry_check=lambda:check(account),
            on_retry=(lambda reason:notify_retry(account,reason)) if notify_retry else None,
            on_recovered=(lambda:notify_recovered(account)) if notify_recovered else None)
        done.append(account)
    return dict(result,status='SUCCEEDED_WITH_SKIPS' if result.get('allowed_skips') else ('SUCCEEDED' if done else result['status']),
        account_order=['a',*order],completed_small_accounts=done,
        small_accounts_verified=order)


def run_scheduled_tail(result,config,root,state):
    from cloud_account_runtime import resolve_context
    from cloud_weekly_chain import execute_stage
    from cloud_failure_notice import notify_retry,notify_recovered,notify_failure
    from cloud_daily_policy import PendingClaim
    import json
    def check(account):
        paths,settings=resolve_context(root,account)
        registry=json.loads((state/'accounts/registry.json').read_text(encoding='utf-8'))
        entry=next(a for a in registry['accounts'] if a['id']==account)
        if not entry.get('expected_uid_hash'):raise RuntimeError(account+' identity is not bound')
        if settings.get('reward_multiplier')!=2:raise RuntimeError(account+' must use double rewards')
        if (state/'stop-request').exists() or (paths.state/'stop-request').exists():
            raise RuntimeError('local_stop_request')
        PendingClaim(paths.pending_claim).assert_clear()
    try:
        return run_tail(result,state,
            lambda account,owner:execute_stage('daily',week_key(),owner,0,1500,config,root,
                account_paths(state,account).state,account=account),check,
            lambda a,e:notify_retry(state,a.upper()+' daily',e),
            lambda a:notify_recovered(state,a.upper()+' daily'),
            order=small_account_order(config))
    except Exception as exc:
        notify_failure(state,'B/C daily',str(exc))
        exc.notified=True
        raise
