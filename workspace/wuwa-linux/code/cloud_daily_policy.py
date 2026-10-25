"""Cloud claims use only solvent, accepting the game's required refill count."""
import re


class ForgeryClaimBudget:
    """Explicit bounded trial; normal daily behavior is unchanged."""
    def __init__(self, rounds):
        if rounds not in (1, 2, 3):
            raise ValueError('Forgery trial requires 1..3 claims')
        self.rounds = rounds
        self.completed = 0

    def before_claim(self, once):
        if once != 40 or self.completed >= self.rounds:
            raise RuntimeError('Forgery trial spending limit reached or wrong domain cost')

    def verified(self, cost):
        if cost != 80 or self.completed >= self.rounds:
            raise RuntimeError('Unexpected trial claim')
        self.completed += 1
        print(f'CLOUD_FORGERY_VERIFIED round={self.completed}/{self.rounds} cost={cost}', flush=True)
        return self.completed < self.rounds, cost


def authorize_selection(kind, text):
    text = re.sub(r'\s+', '', text)
    if any(word in text for word in ('星声', '月相', 'Astrite')):
        raise RuntimeError('Premium currency refill forbidden')
    required = {'solvent':'消耗1结晶溶剂补充60结晶波片'}
    if kind not in required or required[kind] not in text:
        raise RuntimeError('Selected stamina material is not positively verified')


def text_in(task, rect):
    return ''.join(box.name for box in task.ocr(*rect))


def require_text(task, text, rect):
    return task.wait_until(lambda: text in re.sub(r'\s+', '', text_in(task,rect)),
                           time_out=5, raise_if_not_found=True)


def number_in(task, rect):
    value=re.sub(r'\s+', '', text_in(task,rect))
    if not value.isdecimal():
        raise RuntimeError(f'Expected one inventory count, got {value!r}')
    return int(value)


def click_double_claim(task):
    boxes=task.ocr(.56,.58,.76,.67,match=re.compile('双倍领取|雙倍領取'))
    if len(boxes)!=1:
        raise RuntimeError('Double reward button not positively identified')
    task.click_box(boxes[0],after_sleep=1)


def click_single_claim(task):
    boxes=task.ocr(.24,.58,.47,.67,match=re.compile(r'^(?:领取|領取|单倍领取|單倍領取)$'))
    if len(boxes)!=1:
        raise RuntimeError('Single reward button not positively identified')
    task.click_box(boxes[0],after_sleep=1)


def select_solvent(task, title, selection):
    """Only retry reversible selection; never dispatch an exchange here."""
    def selected():
        text = text_in(task, selection)
        # Premium text is a hard stop even during an animation.
        compact = re.sub(r'\s+', '', text)
        if any(word in compact for word in ('星声', '月相', 'Astrite')):
            raise RuntimeError('Premium currency refill forbidden')
        try:
            authorize_selection('solvent', text)
            return True
        except RuntimeError:
            return False
    for _ in range(3):
        require_text(task, '补充结晶波片', title)
        task.sleep(.6)
        task.click_relative(635/1280, 310/720, after_sleep=.6)
        if task.wait_until(selected, time_out=2, raise_if_not_found=False):
            # A fresh second read must still name the exact permitted material.
            task.sleep(.2)
            authorize_selection('solvent', text_in(task, selection))
            return
    raise RuntimeError('Selected stamina material is not positively verified')


def parse_solvent_exchange(label, solvent, reward, current, target):
    label, solvent, reward = (re.sub(r'\s+', '', v) for v in (label, solvent, reward))
    match = re.fullmatch(r'兑换次数[:：]?(\d+)', label)
    if not match:
        raise RuntimeError('Solvent quantity unreadable')
    units = int(match[1])
    amount = units * 60
    if units not in (1, 2) or not target <= current + amount < target + 60:
        raise RuntimeError('Game-selected quantity does not match pending claim')
    if (not re.fullmatch(rf'结晶溶剂[xX×]?{units}', solvent)
            or not re.fullmatch(rf'结晶波片[xX×]?{amount}', reward)):
        raise RuntimeError('Exchange is not the expected solvent amount')
    return units, amount


def verified_solvent_exchange(task, current, target):
    """Wait for two complete labels after the exchange panel animation."""
    import cv2
    previous = None
    def observe():
        nonlocal previous
        task.next_frame()
        frame = cv2.resize(task.frame, None, fx=2, fy=2)
        def read(rect):
            return ''.join(b.name for b in task.ocr(*rect, frame=frame))
        try:
            value = parse_solvent_exchange(
                read((.25, .56, .4, .60)), read((.29, .43, .45, .50)),
                read((.56, .43, .71, .50)), current, target)
        except RuntimeError:
            previous = None
            return False
        if value == previous:
            return value
        previous = value
        task.sleep(.3)
        return False
    return task.wait_until(observe, time_out=5, raise_if_not_found=True)


def refill(task, target, inventory=None, panel_open=False):
    title=(.18,.17,.48,.23)
    selection=(.35,.52,.67,.59)
    premium_rect=(.74,.035,.80,.085)
    current,reserve=(inventory if inventory is not None else task.get_stamina()[:2])
    if current < 0 or reserve < 0:
        raise RuntimeError('Stamina inventory unreadable')
    for attempt in range(5):
        if current >= target:
            return
        old_current,old_reserve=current,reserve
        if not panel_open:
            task.click_relative((1059 if task.has_claim_stamina() else 994)/1280,43/720,after_sleep=.5)
        panel_open=False
        require_text(task,'补充结晶波片',title)
        premium=number_in(task,premium_rect)
        kind='solvent'
        # Deliberately no coordinate or branch selecting the third card.
        select_solvent(task, title, selection)
        task.click_relative(887/1280,520/720,after_sleep=.5)
        require_text(task,'兑换结晶波片',title)
        # Keep the game's selected quantity and require two fresh complete
        # material/amount reads; the low-contrast opening frame is not final.
        units,amount=verified_solvent_exchange(task,current,target)
        task.sleep(1)
        require_text(task,'兑换结晶波片',title)
        if verified_solvent_exchange(task,current,target)!=(units,amount):
            raise RuntimeError('Exchange changed before confirmation')
        task.click_relative(887/1280,520/720,after_sleep=.6)
        # Solvent can show an obtained-item overlay before the
        # selection panel returns. Dismiss only that positively identified UI.
        if task.wait_until(lambda:'获得' in text_in(task,(.4,.21,.6,.29)),time_out=2):
            require_text(task,'点击空白处继续',(.35,.81,.65,.93))
            task.click_relative(.5,.88,after_sleep=.5)
        # Reward-origin refills return directly to the claim dialog after the
        # obtained overlay. Reopen selection only to verify premium inventory.
        task.wait_until(lambda:task.has_claim_stamina() or '补充结晶波片' in text_in(task,title),
                        time_out=5,raise_if_not_found=True)
        if task.has_claim_stamina():
            task.click_relative(1059/1280,43/720,after_sleep=.5)
        require_text(task,'补充结晶波片',title)
        if number_in(task,premium_rect)!=premium:
            raise RuntimeError('Premium inventory changed; stopping immediately')
        # The close icon can ignore a click during the panel animation. Never
        # read native HUD inventory while this panel is still covering it.
        close_refill_panel(task)
        current,reserve,_=task.get_stamina()
        if not old_current+amount <= current <= old_current+amount+1:
            raise RuntimeError('Stamina refill amount did not match the plan')
        if reserve!=old_reserve:
            raise RuntimeError('Reserve inventory changed; solvent-only policy violated')
        task.log_info(f'Cloud refill verified source={kind} amount={amount}; premium unchanged')
    raise RuntimeError('Stamina refill retry limit reached')


def close_refill_panel(task):
    title=(.18,.17,.48,.23)
    for _ in range(3):
        if '补充结晶波片' not in text_in(task,title):
            return
        task.sleep(.6)
        # Explicit Cancel only closes selection; it cannot exchange material.
        task.click_relative(383/1280,520/720,after_sleep=.6)
        if task.wait_until(lambda:'补充结晶波片' not in text_in(task,title),time_out=2):
            return
    raise RuntimeError('Refill selection did not close; refusing HUD inventory read')



class PendingClaim:
    """A process restart must not silently replay an uncertain spending action."""
    def __init__(self, path):
        from pathlib import Path
        self.path = Path(path)

    def assert_clear(self):
        if self.path.exists():
            raise RuntimeError('Unverified previous refill/claim: reconcile game inventory before retrying')

    def begin(self, current, reserve, cost):
        import json
        import os
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create also prevents two task owners from spending together.
        with self.path.open('x', encoding='utf-8') as stream:
            json.dump(dict(current=current, reserve=reserve, cost=cost), stream)
            stream.flush()
            os.fsync(stream.fileno())

    def complete(self):
        import os
        os.replace(self.path, self.path.with_suffix('.last-verified.json'))


def verified_inventory(task):
    """Reject the upstream OCR's missing-current -> zero fallback for spending."""
    # Keep OCR boxes separate: joining reserve "53" and "65/240"
    # produces a false current inventory of 5365.
    texts = [box.name for box in task.ocr(.49, 0, .92, .10)]
    currents = [value for text in texts
                for value in re.findall(r'(\d+)\s*[/／]\s*\d+', text)]
    current, reserve, _ = task.get_stamina()
    if len(currents) != 1 or int(currents[0]) != current or current < 0 or reserve < 0:
        raise RuntimeError(f'Current stamina is not positively readable: boxes={texts!r}, native={current}')
    return current, reserve


def verify_claim(task, before, reserve, cost):
    def verified():
        if task.has_claim_stamina():
            return False
        # Both result controls and a real deduction are required. A timeout
        # leaves the pending marker; never click Claim again to resolve doubt.
        text = text_in(task, (.25, .75, .85, .95))
        if not re.search('重新挑战|再次挑战|再次挑戰', text) or not re.search('退出|离开|離開', text):
            return False
        # The result screen hides the top inventory HUD. Its own remaining
        # stamina label is the authoritative deduction evidence here.
        remaining = re.findall(r'剩[余餘]\s*(\d+)', text)
        accepted = len(remaining) == 1 and before-cost <= int(remaining[0]) <= before-cost+1
        if accepted:task._cloud_last_claim_remaining=int(remaining[0])
        return accepted
    task.wait_until(verified, time_out=8, raise_if_not_found=True)


def claim(task, journal, once=60, must_use=0, multiplier=2):
    from cloud_victory_checkpoint import for_task
    checkpoint=for_task(task)
    saved=checkpoint.assert_resume() if checkpoint else None
    if saved and saved['task'] != type(task).__name__:
        raise RuntimeError('Saved victory task mismatch before spending')
    if once not in (40, 60):
        raise RuntimeError('Unsupported cloud reward cost')
    if type(multiplier) is not int or multiplier not in (1,2):
        raise RuntimeError('Unsupported claim multiplier')
    journal.assert_clear()
    task.sleep(1)
    current, reserve = verified_inventory(task)
    if not task.has_claim_stamina():
        raise RuntimeError('Expected reward dialog')
    cost = once * multiplier
    if getattr(task, '_cloud_daily_no_refill', False) and current < cost:
        if current >= once and must_use <= once:
            multiplier = 1
            cost = once
        else:
            raise RuntimeError('Daily natural waveplates insufficient; reserve/solvent/premium refill blocked before claim')
    click_claim = click_single_claim if multiplier == 1 else click_double_claim
    from claim_receipts import before as evidence_before, after as evidence_after
    evidence=evidence_before(task)
    journal.begin(current, reserve, cost)
    click_claim(task)
    if current < cost:
        if task.has_claim_stamina():
            task.click_relative(1059/1280, 43/720, after_sleep=.5)
        require_text(task, '补充结晶波片', (.18, .17, .48, .23))
        refill(task, cost, inventory=(current, reserve), panel_open=True)
        if not task.has_claim_stamina():
            raise RuntimeError('Expected reward claim after permitted refill')
        current, after_reserve = verified_inventory(task)
        if after_reserve != reserve or current < cost:
            raise RuntimeError('Refill inventory mismatch')
        click_claim(task)
    verify_claim(task, current, reserve, cost)
    receipt=evidence_after(task,evidence,current,reserve,cost)
    from cloud_victory_checkpoint import for_task
    checkpoint=for_task(task)
    if checkpoint:checkpoint.complete(receipt)
    journal.complete()
    # Native farm loop owns progress and recovery. A standalone task does one
    # double claim; DailyTask supplies its remaining 180-point requirement.
    return must_use > cost, cost


def install(pending_path):
    from src.task.BaseWWTask import BaseWWTask
    from src.task.DomainTask import DomainTask
    from src.task.TacetTask import TacetTask
    if getattr(BaseWWTask, '_cloud_claim_policy', False):
        return
    original_use = BaseWWTask.use_stamina
    journal = PendingClaim(pending_path)
    original_inventory = DomainTask.open_F2_book_and_get_stamina
    original_tacet_book = TacetTask.openF2Book

    def domain_inventory(self, inventory=None):
        from cloud_victory_checkpoint import assert_new_entry
        assert_new_entry(self)
        if inventory is None:
            inventory = original_inventory(self)
        if (not self.is_browser() or (getattr(self, '_cloud_forgery_budget', None) is None
                and not getattr(self, '_cloud_allow_solvent_entry', False))
                or inventory[0] >= self.stamina_once):
            return inventory
        journal.assert_clear()
        current, reserve = verified_inventory(self)
        if current < self.stamina_once:
            journal.begin(current,reserve,0)
            refill(self,self.stamina_once,inventory=(current,reserve))
            current,after_reserve=verified_inventory(self)
            if current < self.stamina_once or after_reserve != reserve:
                raise RuntimeError('Pre-entry refill not verified')
            journal.complete()
            self.log_info('Cloud pre-entry solvent refill verified')
        return current,reserve,current+reserve

    def tacet_book(self, feature='gray_book_all_monsters', *args, **kwargs):
        from cloud_victory_checkpoint import assert_new_entry
        assert_new_entry(self)
        result = original_tacet_book(self, feature, *args, **kwargs)
        if (feature == 'gray_book_boss' and self.is_browser()
                and getattr(self, '_cloud_allow_solvent_entry', False)):
            # Tacet uses its own book/entry loop rather than DomainTask's hook.
            domain_inventory(self, self.get_stamina())
        return result

    def use_stamina(self, once=60, must_use=0):
        if not self.is_browser():
            return original_use(self, once, must_use)
        budget = getattr(self, '_cloud_forgery_budget', None)
        if budget is not None:
            budget.before_claim(once)
        result = claim(self, journal, once, must_use,
                       multiplier=getattr(self, '_cloud_claim_multiplier', 2))
        return budget.verified(result[1]) if budget is not None else result

    BaseWWTask.use_stamina = use_stamina
    DomainTask.open_F2_book_and_get_stamina = domain_inventory
    TacetTask.openF2Book = tacet_book
    BaseWWTask._cloud_claim_policy = True
