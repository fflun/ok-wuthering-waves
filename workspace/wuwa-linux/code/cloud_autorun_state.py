"""At-most-once daily launch receipts, including interrupted-run protection."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path


def day_key(now=None):
    # A configured game-day boundary; one attempt per 04:00..04:00 UTC+8 day.
    now=now or datetime.now(timezone(timedelta(hours=8)))
    return (now.astimezone(timezone(timedelta(hours=8)))-timedelta(hours=4)).date().isoformat()


def week_key(now=None):
    game_date=datetime.fromisoformat(day_key(now)).date()
    return (game_date-timedelta(days=game_date.weekday())).isoformat()


def write_json(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    with temp.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)


def fingerprint(root):
    root=Path(root)
    paths=list(root.glob('cloud_*.py'))+list(root.glob('main_cloud*.py'))+list((root/'src').rglob('*.py'))
    paths.append(root/'chrome-extension/worker.js')
    paths.append(root/'config.py')
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}


class DailyLedger:
    def __init__(self,path):self.path=Path(path)
    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
    def retryable(self,day,max_attempts=2):
        item=self.read().get(day,{})
        return (item.get('status')=='FAILED' and item.get('retry_allowed') is True
                and item.get('attempt_count',1)<max_attempts)
    def begin(self,day,retry_failed=False,max_attempts=2):
        records=self.read()
        if any(record['status']=='RUNNING' for record in records.values()):
            return False,'interrupted_run_needs_review'
        previous=records.get(day)
        if previous and previous.get('status')!='READY' and not (retry_failed and self.retryable(day,max_attempts)):
            return False,'already_attempted'
        history=[] if not previous else previous.get('attempts',[])+[
            {key:value for key,value in previous.items() if key!='attempts'}]
        records[day]={'status':'RUNNING','started_at':datetime.now().astimezone().isoformat(),
                      'attempt_count':1 if previous is None else previous.get('attempt_count',1)+1,
                      'attempts':history}
        write_json(self.path,records)
        return True,'started'
    def own(self,day,run_id):
        records=self.read()
        if records.get(day,{}).get('status')!='RUNNING':raise RuntimeError('No running daily to own')
        records[day]['run_id']=run_id
        write_json(self.path,records)
    def finish(self,day,status,detail='',retry_allowed=False,receipt=None):
        if status not in ('SUCCEEDED','FAILED'):raise ValueError('Invalid terminal status')
        records=self.read()
        if records.get(day,{}).get('status')!='RUNNING':raise RuntimeError('No owned running record')
        records[day].update(status=status,detail=detail,finished_at=datetime.now().astimezone().isoformat(),
                            retry_allowed=bool(status=='FAILED' and retry_allowed))
        if receipt is not None:records[day]['receipt']=receipt
        write_json(self.path,records)


class ProcessLock:
    def __init__(self,path): self.path=Path(path); self.file=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+b')
        if self.path.stat().st_size==0: self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close(); self.file=None
            raise RuntimeError('Another daily runner is active')
        return self
    def __exit__(self,*args):
        if self.file:
            self.file.close(); self.file=None
