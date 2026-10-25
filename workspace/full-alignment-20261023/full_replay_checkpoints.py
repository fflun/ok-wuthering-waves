"""Preserve verified replay stages independently of a later workflow failure."""
import hashlib,json
from pathlib import Path
from cloud_autorun_state import write_json

def read_verified(path, day, stage):
    path=Path(path)
    if not path.exists():return None
    item=json.loads(path.read_text()).get(day,{}).get(stage)
    if item is None:return None
    receipt_path=Path(item['receipt_path'])
    if not receipt_path.is_file() or hashlib.sha256(receipt_path.read_bytes()).hexdigest()!=item['sha256']:
        raise RuntimeError('Replay checkpoint evidence missing or changed')
    receipt=json.loads(receipt_path.read_text())
    if receipt.get('run_id')!=item['run_id'] or item['status']!='VERIFIED':
        raise RuntimeError('Replay checkpoint owner/status mismatch')
    return receipt

def save_verified(path,day,stage,receipt,folder):
    path,folder=Path(path),Path(folder)
    record=json.loads(path.read_text()) if path.exists() else {}
    if stage in record.get(day,{}):raise RuntimeError('Refusing to overwrite completed replay')
    proof=folder/'accepted-replay.json';write_json(proof,receipt)
    record.setdefault(day,{})[stage]={'status':'VERIFIED','run_id':receipt['run_id'],
        'receipt_path':str(proof),'sha256':hashlib.sha256(proof.read_bytes()).hexdigest()}
    write_json(path,record)
