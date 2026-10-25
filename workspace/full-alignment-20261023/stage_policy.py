"""Run required rewards before optional farming; never relabel failure as success."""
class WorkflowStopped(RuntimeError):
    """A shared stop, refresh, deadline or unresolved resource journal."""

def run_plan(plan,boundary,save):
    results={}
    for name,required,action in plan:
        boundary()  # Shared invariants are not a per-task recognition failure.
        try:
            record=action()
            ok=record.get('status') in ('SUCCEEDED','SKIPPED_ALLOWED_FAILURE')
            results[name]={'required':required,'ok':ok,'record':record}
        except WorkflowStopped:
            raise
        except Exception as exc:
            results[name]={'required':required,'ok':False,'status':'FAILED_CONTINUED',
                           'error_type':type(exc).__name__,'error':str(exc)}
        save(results)
    missing=[n for n,r in results.items() if r['required'] and not r['ok']]
    optional=[n for n,r in results.items() if not r['required'] and not r['ok']]
    return {'status':'PARTIAL' if missing else 'SUCCEEDED_WITH_SKIPS' if optional or any(
        r.get('record',{}).get('status')=='SKIPPED_ALLOWED_FAILURE' or
        bool(r.get('record',{}).get('receipt',{}).get('pickup_unconfirmed_allowed')) for r in results.values()) else 'SUCCEEDED',
        'required_complete':not missing,'required_incomplete':missing,'optional_incomplete':optional,
        'stage_results':results}

def completed_weekly(ledger,week,stage):
    """A same-account local receipt is authoritative until next weekly boundary."""
    record=ledger.read().get(week,{}).get(stage,{})
    if record.get('status')!='SUCCEEDED':return None
    return dict(record,completion_source='local_weekly_ledger',completion_week=week)
