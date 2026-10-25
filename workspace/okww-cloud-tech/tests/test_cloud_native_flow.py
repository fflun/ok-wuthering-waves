"""Offline regressions for real native methods and spending-dialog transitions."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from cloud_daily_policy import PendingClaim, claim

ROOT = Path(__file__).resolve().parents[1]


def native_method(file, cls, name, extra=None):
    tree = ast.parse((ROOT/file).read_text(encoding='utf-8'))
    node = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls
                for n in c.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {'logger': Mock(), **(extra or {})}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(file), 'exec'), namespace)
    return namespace[name]


class Dialog:
    def __init__(self, current=5, units=2, ambiguous=False):
        self.current, self.reserve, self.premium = current, 53, 1384
        self.units, self.state = units, 'claim'
        self.ambiguous = ambiguous
        self.clicks, self.exchange_confirms = [], 0

    def sleep(self, *args): pass
    def log_info(self, *args): pass
    def get_stamina(self): return self.current, self.reserve, self.current+self.reserve
    def has_claim_stamina(self): return self.state == 'claim'

    def ocr(self, *rect, match=None):
        text = ''
        if rect == (.49, 0, .92, .10): text = f'{self.current}/240'
        elif rect == (.56,.58,.76,.67) and self.state == 'claim': text = '双倍领取'
        elif rect == (.18,.17,.48,.23):
            text = {'selection':'补充结晶波片','exchange':'兑换结晶波片'}.get(self.state,'')
        elif rect == (.37,.53,.64,.58) and self.state == 'selection': text = '消耗1结晶溶剂补充60结晶波片'
        elif rect == (.74,.035,.80,.085): text = str(self.premium)
        elif rect == (.25,.56,.4,.60): text = f'兑换次数：{self.units}'
        elif rect == (.30,.44,.44,.49): text = f'结晶溶剂×{self.units}'
        elif rect == (.57,.44,.70,.49): text = f'结晶波片×{60*self.units}'
        elif rect == (.4,.21,.6,.29) and self.state == 'obtained': text = '获得'
        elif rect == (.35,.81,.65,.93) and self.state == 'obtained': text = '点击空白处继续'
        elif rect == (.25,.75,.85,.95) and self.state == 'result' and not self.ambiguous: text = f'退出 重新挑战 剩余{self.current}'
        return [SimpleNamespace(name=text)] if text and (match is None or match.search(text)) else []

    def wait_until(self, callback, **kw):
        result = callback()
        if not result and kw.get('raise_if_not_found'):
            raise RuntimeError('Unverified dialog transition')
        return result

    def click_box(self, box, **kw):
        self.clicks.append('double')
        if self.current >= self.cost:
            self.current -= self.cost
            self.state = 'result'

    def click_relative(self, x, y, **kw):
        self.clicks.append((x,y))
        if (x,y) == (1059/1280,43/720): self.state = 'selection'
        elif (x,y) == (635/1280,310/720):
            assert self.state == 'selection'
        elif (x,y) == (887/1280,520/720):
            if self.state == 'selection': self.state = 'exchange'
            elif self.state == 'exchange':
                self.exchange_confirms += 1
                self.current += self.units*60
                self.state = 'obtained'
            else: raise AssertionError(self.state)
        elif (x,y) == (.5,.88): self.state = 'claim'
        elif (x,y) in ((1028/1280,140/720),(383/1280,520/720)):
            assert self.state == 'selection'
            self.state = 'claim'
        else: raise AssertionError((x,y))


class SpendingTests(unittest.TestCase):
    def run_claim(self, current, units, once, remaining):
        with tempfile.TemporaryDirectory() as d:
            journal = PendingClaim(Path(d)/'pending.json')
            task = Dialog(current,units)
            task.cost = once*2
            result = claim(task,journal,once,remaining)
            self.assertEqual(result,(remaining>task.cost,task.cost))
            self.assertFalse(journal.path.exists())
            self.assertTrue(journal.path.with_suffix('.last-verified.json').exists())
            self.assertEqual(task.current,current+60*units-task.cost)
            self.assertEqual(task.reserve,53)
            self.assertEqual(task.premium,1384)
            self.assertEqual(task.exchange_confirms,1 if units else 0)

    def test_accept_game_two_solvents_for_eighty(self): self.run_claim(5,2,40,180)
    def test_one_solvent_for_eighty(self): self.run_claim(45,1,40,100)
    def test_two_solvents_for_one_twenty(self): self.run_claim(0,2,60,180)
    def test_last_daily_claim_stops(self): self.run_claim(100,0,40,20)
    def test_standalone_claim_does_not_loop_refills(self): self.run_claim(140,0,60,0)

    def test_uncertain_claim_survives_process_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'pending.json'
            task = Dialog(100,ambiguous=True)
            task.cost = 80
            with self.assertRaises(RuntimeError): claim(task,PendingClaim(path),40,180)
            self.assertEqual(task.current,20)  # Game spent; no verified result yet.
            calls = list(task.clicks)
            with self.assertRaises(RuntimeError): claim(task,PendingClaim(path),40,180)
            self.assertEqual(task.clicks,calls)
            self.assertEqual(json.loads(path.read_text())['cost'],80)

    def test_wrong_exchange_count_never_confirms_quantity(self):
        with tempfile.TemporaryDirectory() as d:
            task = Dialog(5,1); task.cost = 80
            with self.assertRaises(RuntimeError): claim(task,PendingClaim(Path(d)/'p.json'),40,180)
            self.assertEqual(task.exchange_confirms,0)
            self.assertEqual(task.current,5)


class NativeFlowTests(unittest.TestCase):
    def test_daily_selects_real_forgery_task_and_keeps_reward_sequence(self):
        class Forgery: pass
        class Tacet: pass
        class Simulation: pass
        events = []
        task = Mock()
        method = native_method('src/task/DailyTask.py','DailyTask','run', {
            'WWOneTimeTask':SimpleNamespace(run=lambda t: events.append('start')),
            'ADDITIONAL_TASKS':'Additional Tasks to Run After Daily Task',
            'AUTO_FARM_NIGHTMARE_NEST':'Auto Farm all Nightmare Nest',
            'ForgeryTask':Forgery,'TacetTask':Tacet,'SimulationTask':Simulation})
        def get_task(cls):
            self.assertIs(cls,Forgery)
            return task
        t = SimpleNamespace(validate_additional_tasks=Mock(),ensure_main=Mock(),
            config={'Which to Farm':'Forgery Challenge'},support_tasks=['Tacet Suppression','Forgery Challenge'],
            open_daily=lambda:(80,False),get_task_by_class=get_task,sleep=Mock(),
            claim_daily=lambda:events.append('daily'),claim_mail=lambda:events.append('mail'),
            claim_battle_pass=lambda:events.append('battle_pass'),
            run_additional_tasks=lambda:events.append('additional'),log_info=Mock())
        method(t)
        task.farm_forgery.assert_called_once_with(daily=True,used_stamina=80,config=t.config)
        self.assertEqual(events,['start','daily','mail','battle_pass','additional'])

    def test_healer_and_character_callbacks_remain_native(self):
        class Lost(Exception): pass
        class Dead(Lost): pass
        method = native_method('src/task/BaseCombatTask.py','BaseCombatTask','combat_once',
                               {'NotInCombatException':Lost,'CharDeadException':Dead})
        events = []
        t = SimpleNamespace(wait_combat=lambda **k: True, switch_healer_enabled=lambda: True,
            load_chars=lambda:events.append('load'),switch_healer=lambda:events.append('heal'),
            info={},chars=[],in_combat=Mock(side_effect=[True,False]),
            get_current_char=lambda:SimpleNamespace(perform=lambda:events.append('perform')),
            combat_end=lambda:events.append('end'),wait_in_team_and_world=Mock())
        self.assertTrue(method(t))
        self.assertEqual(events,['load','heal','perform','end','heal'])

    def test_death_reentry_preserves_remaining_stamina(self):
        method = native_method('src/task/DomainTask.py','DomainTask','farm_domain_with_recovery_loop')
        t = SimpleNamespace(stamina_once=40,open_F2_book_and_get_stamina=lambda:(200,0,200),
            farm_in_domain=Mock(side_effect=[(False,100),(True,20)]),sleep=Mock(),log_info=Mock(),
            make_sure_in_world=Mock(),back=Mock())
        teleport = Mock()
        method(t,180,teleport)
        self.assertEqual(teleport.call_count,2)
        self.assertEqual([c.kwargs['must_use'] for c in t.farm_in_domain.call_args_list],[180,100])

    def test_recovery_retries_are_bounded(self):
        method = native_method('src/task/DomainTask.py','DomainTask','farm_domain_with_recovery_loop')
        t = SimpleNamespace(stamina_once=40,open_F2_book_and_get_stamina=lambda:(200,0,200),
            farm_in_domain=Mock(return_value=(False,180)),sleep=Mock(),log_info=Mock(),
            make_sure_in_world=Mock(),back=Mock())
        teleport = Mock()
        method(t,180,teleport)
        self.assertEqual(teleport.call_count,3)
        t.make_sure_in_world.assert_called_once()

    def test_entry_defaults_to_offline_without_runtime(self):
        for entry in ('main_cloud_daily.py','main_cloud.py'):
            r = subprocess.run([sys.executable,'-I',str(ROOT/entry)] if entry == 'main_cloud_daily.py'
                               else [sys.executable,str(ROOT/entry)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertIn('CLOUD_OFFLINE',r.stdout)


if __name__ == '__main__': unittest.main()
