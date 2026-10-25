"""Positive, multi-frame completion evidence for browser material domains."""
from dataclasses import dataclass
import re
import time


class CombatObservationError(RuntimeError):
    """Uncertain combat state must stop the task, not become a victory."""


@dataclass(frozen=True)
class Evidence:
    timer: bool = False
    enemies: bool = False
    unfinished: bool = False
    reward: bool = False
    team: bool = False
    recovery: bool = False
    valid: bool = True


class CompletionGate:
    def __init__(self):
        self.since = None
        self.samples = 0
        self.last_frame = None

    def update(self, evidence, now, frame):
        positive = (evidence.valid and evidence.team and evidence.reward
                    and not any((evidence.timer, evidence.enemies,
                                 evidence.unfinished, evidence.recovery)))
        if not positive:
            self.since, self.samples, self.last_frame = None, 0, None
            if not evidence.valid:
                return 'UNKNOWN'
            if evidence.recovery:
                return 'RECOVERY'
            if evidence.timer or evidence.enemies or evidence.unfinished:
                return 'ACTIVE'
            return 'UNKNOWN'
        if frame is not self.last_frame:
            if self.since is None:
                self.since = now
            self.samples += 1
            self.last_frame = frame
        return 'COMPLETE' if self.samples >= 3 and now-self.since >= 1.0 else 'PENDING'


def applies(task):
    from src.task.DomainTask import DomainTask
    from src.task.TacetTask import TacetTask
    return task.is_browser() and isinstance(task, (DomainTask, TacetTask))


def read_evidence(task):
    frame = task.frame
    if frame is None or frame.mean() < 2 or frame.std() < 2:
        return Evidence(valid=False), frame
    timer = bool(task.ocr(.445, .11, .56, .165,
        match=re.compile(r'\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：.]\s*\d{2})?')))
    objective = ''.join(b.name for b in task.ocr(.01, .20, .34, .32))
    counts = re.findall(r'(\d{1,3})\s*[/／]\s*(\d{1,3})', objective)
    unfinished = any(0 <= int(a) < int(b) for a, b in counts)
    enemies = bool(task.check_health_bar())
    recovery = bool(task.find_one('revive_confirm_hcenter_vcenter', threshold=.8))
    ok, index, count = task.in_team()
    reward = bool(re.search('领取奖励|領取獎勵', objective) or task.find_treasure_icon())
    return Evidence(timer=timer, enemies=enemies, unfinished=unfinished,
                    reward=reward, team=bool(ok and count == 3 and index in (0, 1, 2)),
                    recovery=recovery), frame


def observe(task, *, fresh=False):
    now = time.monotonic()
    state = getattr(task, '_cloud_material_exit', None)
    if state is None:
        state = {'gate': CompletionGate(), 'at': -10, 'status': None}
        task._cloud_material_exit = state
    if not fresh and now-state['at'] < .2:
        return state['status']
    if fresh:
        task.next_frame()
    try:
        evidence, frame = read_evidence(task)
    except Exception as exc:
        # A failed OCR/template/frame read cannot supply negative evidence.
        evidence, frame = Evidence(valid=False), None
        task.log_info(f'CLOUD_MATERIAL observation unavailable: {type(exc).__name__}')
    status = state['gate'].update(evidence, time.monotonic(), frame)
    if status != state['status']:
        task.log_info(f'CLOUD_MATERIAL state={status} evidence={evidence}')
    state.update(at=time.monotonic(), status=status)
    return status


def settled(task, *, fresh=False, timeout=8):
    status = observe(task, fresh=fresh)
    if status in ('ACTIVE', 'COMPLETE', 'RECOVERY'):
        return status
    task.executor.interaction.release_all()
    for recovery_round in range(3):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            # Do not use task.sleep here: its combat callback would recurse.
            time.sleep(.2)
            status = observe(task, fresh=True)
            if status in ('ACTIVE', 'COMPLETE', 'RECOVERY'):
                return status
        if recovery_round == 2:
            break
        from cloud_reward_recovery import recover
        try:
            if not recover(task):break
        except Exception as exc:
            raise CombatObservationError(f'Reward recovery stopped: {exc}') from exc
        status = observe(task, fresh=True)
        if status in ('ACTIVE', 'COMPLETE', 'RECOVERY'):
            return status
    raise CombatObservationError('Combat state uncertain after bounded observation/recovery; no victory or reward action authorized')


def material_active(task):
    # RECOVERY preserves the original death path; it never approves victory.
    return settled(task) == 'ACTIVE'


def require_completion(task, stage):
    # Never reuse the combat exit's approval at the later reward boundary.
    task._cloud_material_exit = None
    status = settled(task, fresh=True)
    if status != 'COMPLETE':
        raise CombatObservationError(f'{stage}: combat completion not confirmed ({status}); reward actions blocked')
    task.log_info(f'CLOUD_MATERIAL completion verified before {stage}')
