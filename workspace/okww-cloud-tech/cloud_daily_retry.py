"""One bounded daily retry; each native run reads live daily progress first."""
import uuid


class DailyStageFailure(RuntimeError):
    def __init__(self,message,retry_allowed=False):
        self.retry_allowed=retry_allowed
        super().__init__(message)


def run_daily(daily,day,execute,boundary,retries=0,retry_check=None,on_retry=None,on_recovered=None):
    if retries not in (0,1):raise ValueError('Daily permits at most one retry')
    for _ in range(retries+1):
        boundary()
        if retry_check:retry_check()
        if _==0 and daily.retryable(day) and on_retry:
            try:on_retry('Resuming the recorded first failure')
            except Exception:pass
        allowed,reason=daily.begin(day,retry_failed=retries==1,max_attempts=2)
        if not allowed:raise DailyStageFailure(reason)
        run_id=uuid.uuid4().hex
        daily.own(day,run_id)
        try:
            receipt=execute(run_id)
            boundary()
            if receipt.get('status')!='SUCCEEDED' or receipt.get('run_id')!=run_id:
                raise DailyStageFailure('Daily did not return its owned successful receipt')
            daily.finish(day,'SUCCEEDED','Native daily completed before following stages',receipt=receipt)
            if daily.read()[day].get('attempt_count',1)>1 and on_recovered:
                try:on_recovered()
                except Exception:pass
            return receipt
        except BaseException as exc:
            retry_allowed=isinstance(exc,Exception) and getattr(exc,'retry_allowed',True)
            try:
                boundary()
                if retry_check:retry_check()
            except BaseException:
                retry_allowed=False
            remaining=daily.read()[day].get('attempt_count',1)<retries+1
            daily.finish(day,'FAILED',str(exc),retry_allowed=retry_allowed and remaining)
            if not (retry_allowed and remaining):raise
            if on_retry:
                try:on_retry(str(exc))
                except Exception:pass
    raise DailyStageFailure('Daily retry exhausted')
