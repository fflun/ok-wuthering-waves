"""Import the installed framework, but never construct OK or start capture/input."""
import inspect
import ast
import subprocess
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.task.BaseWWTask import BaseWWTask
from src.task.BaseCombatTask import BaseCombatTask
from src.task.DailyTask import DailyTask
from src.task.TacetTask import TacetTask
from src.task.DomainTask import DomainTask
from src.task.ForgeryTask import ForgeryTask
from src.combat.CombatCheck import CombatCheck
from cloud_adapter import install

classes = (BaseWWTask, BaseCombatTask, DailyTask, TacetTask, DomainTask, ForgeryTask, CombatCheck)
originals = {(cls, name): method for cls in classes
             for name, method in cls.__dict__.items() if inspect.isfunction(method)}
with tempfile.TemporaryDirectory() as directory:
    install(Path(directory)/'pending.json')
    assert not list(Path(directory).iterdir()), 'Import/install must not write a spending record'
changed = {(cls, name) for (cls, name), method in originals.items() if getattr(cls, name) is not method}
expected = {(BaseWWTask, name) for name in ('use_stamina','find_f_with_claim_text','pick_f',
                                          'find_treasure_icon','walk_to_treasure')}
expected |= {(BaseCombatTask,'combat_end'), (BaseCombatTask,'count_rings'), (DomainTask,'open_F2_book_and_get_stamina')}
assert changed == expected, ('Unexpected/missing hooks', changed ^ expected)
assert issubclass(ForgeryTask, DomainTask)
assert ForgeryTask.revive_action is DomainTask.revive_action
assert TacetTask.combat_once is ForgeryTask.combat_once is BaseCombatTask.combat_once
assert DailyTask.run.__module__ == 'src.task.DailyTask'
root = Path(__file__).resolve().parents[1]
for relative in ['src/task/DomainTask.py', 'src/task/ForgeryTask.py', 'src/task/DailyTask.py'] + [
        str(p.relative_to(root)).replace('\\','/') for p in (root/'src/char').glob('*.py')]:
    import hashlib, json
    expected_hash=json.loads((root.parent/'windows-source-hashes.json').read_text())[relative]
    assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==expected_hash, relative
print('PASS: exact 7 installed hooks verified; original character and domain/daily source retained')
