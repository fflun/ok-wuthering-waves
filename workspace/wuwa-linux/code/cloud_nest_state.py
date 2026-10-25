"""Atomic, account/game-day scoped receipts; live named-book proof is mandatory."""
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TARGET = '落渊南丘残象聚落'
KEY = 'go_nest:41:25'
CLEARED_NEST_CONTINUATION_POLICY = 'verified_cleared_nest_continue_after_bounded_search'
OPTIONAL_PICKUP_TARGET = '陷足流川残象聚落'
UNCONFIRMED_PHASE = 'PICKUP_UNCONFIRMED_ALLOWED'
TERMINAL_PHASES = ('PICKED_UP','SEARCHED_NO_ECHO',UNCONFIRMED_PHASE)


def game_day():
    return (datetime.now(timezone(timedelta(hours=8)))-timedelta(hours=4)).date().isoformat()


def pending_hint(directory, account, day=None):
    account_hash = hashlib.sha256(account.encode()).hexdigest()
    pending = []
    for path in Path(directory).glob('nest-state-*.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('account') == account_hash and record.get('day') == (day or game_day()):
            if record.get('phase') in {'IN_PROGRESS', 'CLEARED_PENDING_PICKUP'}:
                if record.get('total') not in (24,36,41,48) or not record.get('target','').endswith('残象聚落'):
                    raise RuntimeError('Invalid pending nest identity')
                pending.append(record)
    if len(pending) > 1:
        raise RuntimeError('Multiple pending nests; refusing to choose a different location')
    return pending[0] if pending else None


class NestState:
    def __init__(self, path, account, day=None, target=TARGET, key=KEY, total=41):
        self.path = Path(path)
        self.scope = dict(version=1, account=hashlib.sha256(account.encode()).hexdigest(),
                          day=day or game_day(), target=target, key=key, total=total)
        self.record = None

    def reconcile(self, title, first, second):
        total = self.scope['total']
        if title != self.scope['target'] or first != second or first[1] != total or not 0 <= first[0] <= total:
            raise RuntimeError('Nest identity/count not verified twice')
        old = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else None
        if old and all(old.get(k) == v for k, v in self.scope.items()):
            if old.get('phase') not in ('IN_PROGRESS', 'CLEARED_PENDING_PICKUP', *TERMINAL_PHASES):
                raise RuntimeError('Invalid nest receipt phase')
            if old['phase'] != 'IN_PROGRESS' and first != (total, total):
                raise RuntimeError('Live progress conflicts with saved completion; stopped')
            self.record = old
        else:
            self.record = dict(self.scope, phase='IN_PROGRESS')
        self.record['book_count'] = list(first)
        if first == (total, total) and self.record['phase'] not in TERMINAL_PHASES:
            self.record['phase'] = 'CLEARED_PENDING_PICKUP'
            self.record['verified_count'] = [total,total]
        self._write()
        return self.record['phase']

    def cleared(self):
        if self.record is None:
            raise RuntimeError('Cannot save completion without named-book verification')
        if self.record['phase'] not in TERMINAL_PHASES:
            self.record['phase'] = 'CLEARED_PENDING_PICKUP'
            self.record['verified_count'] = [self.scope['total'], self.scope['total']]
            self.record['cleared_at'] = time.time()
            self._write()

    def target_seen(self, first_image, second_image):
        if self.record is None or self.record['phase'] != 'CLEARED_PENDING_PICKUP':
            raise RuntimeError('Target evidence requires verified completion')
        images = []
        for image in (first_image, second_image):
            if image is None or not Path(image).is_file():
                raise RuntimeError('Stable target evidence image missing')
            path = Path(image)
            images.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if images[0]['path'] == images[1]['path']:
            raise RuntimeError('Stable target requires two fresh observations')
        if not self.record.get('unclaimed_target_seen'):
            self.record.update(unclaimed_target_seen=True,
                target_observation=dict(source='original_model_stable_pair', images=images,
                                        observed_at=time.time()))
            self._write()

    def picked(self):
        if self.record is None or self.record['phase'] != 'CLEARED_PENDING_PICKUP':
            raise RuntimeError('Cannot record pickup before verified completion')
        self.record['phase'] = 'PICKED_UP'
        self._write()

    def searched_empty(self,evidence):
        if self.record is None or self.record['phase']!='CLEARED_PENDING_PICKUP':
            raise RuntimeError('Empty search requires verified completion')
        if self.record.get('unclaimed_target_seen'):
            raise RuntimeError('Previously observed target cannot become an empty-search receipt')
        if (evidence.get('target')!=self.scope['target'] or evidence.get('count')!=[self.scope['total']]*2
                or evidence.get('absorb_sent') is not False or evidence.get('stable_target_seen') is not False
                or evidence.get('native_circle_completed') is not True or not evidence.get('image')):
            raise RuntimeError('Empty search evidence incomplete')
        path=Path(evidence['image'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=evidence.get('image_sha256'):
            raise RuntimeError('Empty search image evidence missing or changed')
        self.record.update(phase='SEARCHED_NO_ECHO',pickup_search=evidence,absorbed=False)
        self._write()

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(self.record, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def unconfirmed_allowed(self,evidence):
        if (self.record is None or self.record['phase']!='CLEARED_PENDING_PICKUP'
                or self.scope['target']!=OPTIONAL_PICKUP_TARGET or self.scope['total']!=24):
            raise RuntimeError('Unconfirmed pickup policy is restricted to the verified final nest')
        if (evidence.get('target')!=self.scope['target'] or evidence.get('count')!=[24,24]
                or evidence.get('bounded_search_completed') is not True
                or evidence.get('user_policy')!='final_nest_ignore_unconfirmed_absorption'
                or not isinstance(evidence.get('absorb_sent'),bool)):
            raise RuntimeError('Unconfirmed pickup evidence incomplete')
        path=Path(evidence.get('image',''))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=evidence.get('image_sha256'):
            raise RuntimeError('Unconfirmed pickup image missing or changed')
        self.record.update(phase=UNCONFIRMED_PHASE,pickup_search=evidence,absorbed=False,
                           absorption_status='UNCONFIRMED',continuation_authorized=True)
        self._write()


    def continue_after_search(self,evidence):
        """User-authorized continuation; does not certify echo absorption."""
        if self.record is None or self.record['phase']!='CLEARED_PENDING_PICKUP':
            raise RuntimeError('Continuation requires verified cleared nest')
        if (self.scope['total'] not in (24,36,41,48)
                or evidence.get('target')!=self.scope['target']
                or evidence.get('count')!=[self.scope['total']]*2
                or evidence.get('bounded_search_completed') is not True
                or evidence.get('user_policy')!=CLEARED_NEST_CONTINUATION_POLICY
                or not isinstance(evidence.get('absorb_sent'),bool)):
            raise RuntimeError('Cleared-nest continuation evidence incomplete')
        path=Path(evidence.get('image',''))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=evidence.get('image_sha256'):
            raise RuntimeError('Cleared-nest continuation image missing or changed')
        self.record.update(phase=UNCONFIRMED_PHASE,pickup_search=evidence,absorbed=False,
                           absorption_status='UNCONFIRMED',continuation_authorized=True)
        self._write()
