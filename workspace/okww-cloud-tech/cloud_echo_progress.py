"""Account/day scoped boss victories and completed native pickup searches."""
import hashlib
import json
from pathlib import Path
import time
from cloud_autorun_state import day_key,write_json
import re


def resume_scene(task, pending=False):
    """Inspect the same boss before ensure_main can exit its pending loot."""
    task.next_frame()
    title=''.join(box.name for box in task.ocr(.30,0,.72,.075))
    expected='80' in title and ('天演溯心' in title or '衍律化形' in title)
    reward=bool(task.ocr(.01,.21,.25,.31,match=re.compile('领取奖励|領取獎勵')))
    active=bool(task.ocr(.01,.21,.25,.31,match=re.compile('击败敌人|擊敗敵人')))
    victory=expected and reward
    if pending:
        if active or (title and not expected):
            raise RuntimeError('Pending boss pickup conflicts with current battle; no navigation sent')
        # Victory removes the boss title; reconnect can also remove its objective.
        # This permits pickup SEARCH only, based on a persisted verified victory.
        # EchoProgress validates account ownership before any input. No fresh
        # victory is inferred from missing UI; F still requires an absorb label.
        ok,index,count=task.in_team()
        if not ok or count!=3:raise RuntimeError('Pending boss pickup lacks playable team HUD; no navigation sent')
        return 'victory' if reward else 'pending_search_only'
    if victory:return 'victory'
    if expected and active:return 'active'
    return None


class EchoProgress:
    def __init__(self,path,account,day,target='weekly-list-1-level-80'):
        self.path=Path(path)
        if not isinstance(target,str) or not target.strip():raise ValueError('Explicit boss target required')
        self.scope=dict(version=1,account=hashlib.sha256(account.encode()).hexdigest(),game_day=day,
                        target=target,goal=20)
        if self.path.exists():
            self.record=json.loads(self.path.read_text(encoding='utf-8'))
            if any(self.record.get(k)!=v for k,v in self.scope.items()):
                raise RuntimeError('Boss progress belongs to another account/day/target')
        else:self.record=dict(self.scope,rounds=[],pending=None)
        rounds=self.record['rounds']
        if [r['round'] for r in rounds]!=list(range(1,len(rounds)+1)) or len(rounds)>20:
            raise RuntimeError('Boss progress sequence is invalid')
        if self.record['pending'] and self.record['pending']['round']!=len(rounds)+1:
            raise RuntimeError('Pending boss pickup conflicts with completed rounds')
    @property
    def completed(self):return len(self.record['rounds'])
    @property
    def pending(self):return self.record['pending']
    def assert_day(self):
        if day_key()!=self.scope['game_day']:raise RuntimeError('Boss progress crossed game refresh')
    def victory(self,run_id,image):
        self.assert_day()
        if self.pending or self.completed>=20:raise RuntimeError('Unfinished pickup or boss quota exhausted')
        self.record['pending']=dict(round=self.completed+1,run_id=run_id,victory_image=image,verified_at=time.time())
        write_json(self.path,self.record)
    def pickup_finished(self,dropped,image):
        self.assert_day()
        if not self.pending:raise RuntimeError('Pickup search has no verified boss victory')
        self.record['rounds'].append(dict(self.pending,pickup_search_completed=True,
            absorbed=bool(dropped),pickup_image=image,completed_at=time.time()))
        self.record['pending']=None;write_json(self.path,self.record)


def verified_boss_progress(path,day):
    record=json.loads(Path(path).read_text(encoding='utf-8'))
    rounds=record.get('rounds',[])
    if (record.get('version')!=1 or record.get('game_day')!=day
            or record.get('target')!='weekly-list-1-level-80' or record.get('goal')!=20
            or record.get('pending') or len(rounds)!=20
            or [r.get('round') for r in rounds]!=list(range(1,21))
            or any(r.get('pickup_search_completed') is not True or not r.get('run_id')
                   or not r.get('victory_image') or not r.get('pickup_image') for r in rounds)):
        raise RuntimeError('Twenty boss rounds and pickup searches are not verified')
    return record
