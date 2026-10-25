"""Weekly receipts; caller owns runner.lock, including its awaited child."""
from datetime import datetime,timezone,timedelta
import hashlib
import os
from pathlib import Path
import time

from cloud_autorun_state import week_key,write_json
import json

STAGES=('boss','garden')


class WeeklyLedger:
    def __init__(self,path):self.path=Path(path)
    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
    def blocked(self):
        return any(item.get('status')=='RUNNING' for stages in self.read().values() for item in stages.values())
    def retryable(self,week,stage):
        item=self.read().get(week,{}).get(stage,{})
        return item.get('status')=='FAILED' and item.get('retry_allowed') is True and item.get('attempt_count',1)<2
    def begin(self,week,stage,run_id,started_at=None,retry_failed=False):
        if stage not in STAGES:raise ValueError('Unknown weekly stage')
        records=self.read();old=records.get(week,{}).get(stage,{})
        if old.get('status')=='SUCCEEDED':return False
        if self.blocked():raise RuntimeError('Interrupted weekly run needs review')
        if old.get('status') in ('FAILED','RUNNING') and not (retry_failed and self.retryable(week,stage)):raise RuntimeError('Weekly failure needs explicit review')
        history=old.get('history',[])
        if old.get('status')=='FAILED':history=history+[{k:v for k,v in old.items() if k not in ('history','claims')}]
        records.setdefault(week,{})[stage]=dict(status='RUNNING',run_id=run_id,
            started_at=time.time() if started_at is None else started_at,
            claims=old.get('claims',[]),history=history,
            attempt_count=old.get('attempt_count',1)+1 if old.get('status')=='FAILED' else 1)
        write_json(self.path,records);return True
    def owned(self,records,week,stage,run_id):
        item=records.get(week,{}).get(stage,{})
        if item.get('status')!='RUNNING' or item.get('run_id')!=run_id:
            raise RuntimeError('Weekly receipt does not belong to the active run')
        return item
    def claim(self,week,run_id,evidence):
        records=self.read();item=self.owned(records,week,'boss',run_id)
        claims=item['claims']
        if len(claims)>=3:raise RuntimeError('Weekly claim quota already recorded')
        if evidence.get('claim_id') in {c['claim_id'] for c in claims}:
            raise RuntimeError('Duplicate weekly claim receipt')
        stamp=evidence.get('verified_at',0)
        if (evidence.get('status')!='CLAIM_VERIFIED' or evidence.get('cost')!=60
                or not evidence.get('claim_id') or stamp<item['started_at']
                or week_key(datetime.fromtimestamp(stamp,timezone.utc))!=week):
            raise RuntimeError('Weekly claim evidence is invalid')
        claims.append(evidence);write_json(self.path,records)
    def finish(self,week,stage,run_id,receipt):
        records=self.read();item=self.owned(records,week,stage,run_id)
        if (receipt.get('status')!='SUCCEEDED' or receipt.get('run_id')!=run_id
                or receipt.get('game_week')!=week
                or receipt.get('completed_at',0)<item['started_at']):
            raise RuntimeError('Weekly completion receipt is stale or unowned')
        if stage=='boss' and len(item['claims'])!=3:
            raise RuntimeError('All three weekly material claims must be verified')
        if stage=='garden' and (receipt.get('current')!=6000 or receipt.get('target')!=6000
                                 or receipt.get('verified_rewards')!=6):
            raise RuntimeError('Garden progress and all six rewards must be verified')
        item.update(status='SUCCEEDED',completed_at=receipt['completed_at'],receipt=receipt)
        write_json(self.path,records)
    def fail(self,week,stage,run_id,error,retry_allowed=False):
        records=self.read();item=self.owned(records,week,stage,run_id)
        item.update(status='FAILED',error=str(error),failed_at=time.time(),retry_allowed=retry_allowed)
        write_json(self.path,records)
    def authorize_resume_after_review(self,week,stage):
        # Only call after a human reviews the game quota and any pending claim.
        records=self.read();item=records.get(week,{}).get(stage,{})
        if item.get('status') not in ('FAILED','RUNNING'):raise RuntimeError('No failed run to review')
        item.setdefault('history',[]).append({k:v for k,v in item.items() if k not in ('history','claims')})
        item['status']='READY';write_json(self.path,records)
    def import_verified(self,stage,evidence_path):
        path=Path(evidence_path);e=json.loads(path.read_text(encoding='utf-8'))
        if stage=='boss':
            claims=e.get('claims',[]);week=e.get('game_week')
            if (e.get('status')!='THREE_WEEKLY_MATERIAL_CLAIMS_VERIFIED' or len(claims)!=3
                    or {c.get('round') for c in claims}!={1,2,3}
                    or any(c.get('status')!='CLAIM_VERIFIED' or c.get('cost')!=60
                           or week_key(datetime.fromtimestamp(c.get('verified_at',0),timezone.utc))!=week for c in claims)):
                raise RuntimeError('Historical weekly boss evidence is incomplete')
        elif stage=='garden':
            week=week_key(datetime.fromisoformat(e['game_day']).replace(hour=12,tzinfo=timezone(timedelta(hours=8))))
            if e.get('status')!='SUCCEEDED' or e.get('current')!=6000 or e.get('target')!=6000 or e.get('verified_rewards')!=6:
                raise RuntimeError('Historical garden evidence is incomplete')
            claims=[]
        else:raise ValueError('Unknown weekly stage')
        records=self.read()
        if stage in records.get(week,{}):return False
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if stage=='boss':claims=[dict(c,claim_id='history:'+digest+':'+str(c['round'])) for c in claims]
        records.setdefault(week,{})[stage]=dict(status='SUCCEEDED',claims=claims,
            imported_from=str(path),evidence_sha256=digest,receipt=e)
        write_json(self.path,records);return True


def assert_expected_week():
    expected=os.environ.get('OKWW_WEEKLY_WEEK')
    if expected and week_key()!=expected:raise RuntimeError('Weekly refresh occurred; stop for review')


def record_live_boss_claim(image,number):
    assert_expected_week()
    path=os.environ.get('OKWW_WEEKLY_LEDGER')
    if not path:return
    run_id=os.environ['OKWW_WEEKLY_RUN_ID'];week=os.environ['OKWW_WEEKLY_WEEK']
    WeeklyLedger(path).claim(week,run_id,dict(status='CLAIM_VERIFIED',cost=60,
        claim_id=run_id+':'+str(number),verified_at=time.time(),image=str(image),
        image_sha256=hashlib.sha256(Path(image).read_bytes()).hexdigest()))
