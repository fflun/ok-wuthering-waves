"""Durable, fail-closed daily victory checkpoint; never grants gameplay input."""
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def game_day():
    return (datetime.now(timezone(timedelta(hours=8))) - timedelta(hours=4)).date().isoformat()


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class VictoryCheckpoint:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return None
        value = json.loads(self.path.read_text(encoding='utf-8'))
        if (value.get('schema') != 1 or value.get('status') not in
                ('WON_UNCLAIMED', 'LOST_UNCLAIMED', 'CLAIM_VERIFIED')
                or not value.get('game_day') or not value.get('id')):
            raise RuntimeError('Invalid victory checkpoint; manual reconciliation required')
        return value

    def pending(self):
        value = self.read()
        if value and value['status'] != 'CLAIM_VERIFIED':
            return value
        return None

    def assert_new_entry(self):
        if self.pending():
            raise RuntimeError('Unclaimed victory exists; new battle/navigation blocked, including across game days')

    def assert_resume(self):
        value = self.pending()
        if value and (value['status'] != 'WON_UNCLAIMED' or value['game_day'] != game_day()):
            raise RuntimeError('Lost or previous-day unclaimed victory; explicit reconciliation required')
        return value

    def record_win(self, task, image):
        existing = self.assert_resume()
        if existing:
            if existing['task'] != task:
                raise RuntimeError('Victory task identity changed')
            return existing
        previous = self.read()
        if previous:
            atomic_write(self.path.parent / 'victory-history' / (previous['id'] + '.json'), previous)
        image = Path(image)
        value = dict(schema=1, id=str(time.time_ns()), game_day=game_day(),
                     run_id=os.environ.get('OKWW_RUN_ID'), task=task,
                     status='WON_UNCLAIMED', won_at=time.time(), image=str(image),
                     image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        atomic_write(self.path, value)
        return value

    def complete(self, receipt):
        value = self.assert_resume()
        if not value:
            return
        if not isinstance(receipt, dict) or receipt.get('deduction_verified') is not True:
            raise RuntimeError('Cannot clear victory without verified claim receipt')
        before, cost, remaining = (receipt.get(k) for k in ('before', 'cost', 'remaining'))
        if (not all(type(x) is int for x in (before, cost, remaining))
                or cost not in (40, 60, 80, 120) or not before-cost <= remaining <= before-cost+1
                or receipt.get('at', 0) < value['won_at']):
            raise RuntimeError('Claim receipt does not reconcile saved victory')
        for key in ('before_image', 'after_image'):
            if not Path(receipt.get(key, '')).is_file():
                raise RuntimeError('Missing claim evidence image')
        value.update(status='CLAIM_VERIFIED', receipt=receipt, verified_at=time.time())
        atomic_write(self.path, value)


def for_task(task):
    path = getattr(task, '_cloud_victory_path', None)
    return VictoryCheckpoint(path) if path else None


def assert_new_entry(task):
    checkpoint = for_task(task)
    if checkpoint:
        checkpoint.assert_new_entry()


def save_completion(task, stage):
    checkpoint = for_task(task)
    if not checkpoint:
        return
    existing = checkpoint.assert_resume()
    if existing:
        if existing['task'] != type(task).__name__:
            raise RuntimeError('Victory task identity changed')
        return
    import cv2
    image = checkpoint.path.parent / 'victory-evidence' / (str(time.time_ns()) + '.png')
    image.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(image), task.frame):
        raise RuntimeError('Cannot persist victory evidence; reward navigation blocked')
    checkpoint.record_win(type(task).__name__, image)
    task.log_info('CLOUD_VICTORY_SAVED before ' + stage)
