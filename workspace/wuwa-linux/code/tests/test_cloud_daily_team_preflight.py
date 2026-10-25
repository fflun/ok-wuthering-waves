import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from contextlib import nullcontext
from main_cloud_daily import prepare_daily_team,prepare_nest_team


class DailyTeamPreflightTests(unittest.TestCase):
    def test_nest_closes_identity_menu_before_two_world_frames(self):
        events=[]
        active=SimpleNamespace(ensure_main=Mock(side_effect=lambda **k:events.append('return')),
            next_frame=Mock(side_effect=lambda:events.append('frame')),
            in_team_and_world=Mock(side_effect=lambda:(events.append('world') or True)),sleep=Mock())
        with TemporaryDirectory() as directory:prepare_nest_team(active,Path(directory)/'claim-pending.json')
        self.assertEqual(events,['return','frame','world','frame','world'])
    def test_nest_menu_or_changed_world_is_rejected(self):
        for reads in ([False],[True,False]):
            active=SimpleNamespace(ensure_main=Mock(),next_frame=Mock(),in_team_and_world=Mock(side_effect=reads),sleep=Mock())
            with TemporaryDirectory() as directory:
                with self.assertRaisesRegex(RuntimeError,'world'):prepare_nest_team(active,Path(directory)/'claim-pending.json')
    def test_nest_pending_prevents_menu_input(self):
        active=SimpleNamespace(ensure_main=Mock(),next_frame=Mock(),ocr=Mock(return_value=[]))
        with TemporaryDirectory() as directory:
            pending=Path(directory)/'claim-pending.json';pending.write_text('{}')
            with self.assertRaises(RuntimeError):prepare_nest_team(active,pending)
        active.ensure_main.assert_not_called()
    def test_nest_scope_after_identity_before_strict_team_gate(self):
        tree=ast.parse((Path(__file__).parents[1]/'main_cloud_daily.py').read_text(encoding='utf-8'))
        wrapper=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='account_run')
        calls={n.func.id:n.lineno for n in ast.walk(wrapper) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertLess(calls['verify_account_identity'],calls['prepare_nest_team'])
        self.assertLess(calls['prepare_nest_team'],calls['verify_task_team'])
        gate=next(n for n in ast.walk(wrapper) if isinstance(n,ast.If) and any(isinstance(c,ast.Call) and isinstance(c.func,ast.Name) and c.func.id=='prepare_nest_team' for c in ast.walk(n)))
        self.assertEqual(ast.unparse(gate.test),"args.account == 'a' and args.task == 'nightmare'")
    def test_full_health_before_character_loading(self):
        active=SimpleNamespace(ensure_main=Mock(),next_frame=Mock(),ocr=Mock(return_value=[]))
        with TemporaryDirectory() as directory, patch('cloud_revive.recovery_navigation',return_value=nullcontext()), patch('cloud_revive.world_heal_and_reenter') as heal:
            prepare_daily_team(active,Path(directory)/'claim-pending.json')
        active.ensure_main.assert_called_once_with(time_out=60)
        heal.assert_called_once_with(active,reenter=False)

    def test_pending_prevents_heal(self):
        active=SimpleNamespace(ensure_main=Mock(),next_frame=Mock(),ocr=Mock(return_value=[]))
        with TemporaryDirectory() as directory, patch('cloud_revive.world_heal_and_reenter') as heal:
            pending=Path(directory)/'claim-pending.json';pending.write_text('{}')
            with self.assertRaises(RuntimeError):prepare_daily_team(active,pending)
        active.ensure_main.assert_not_called();heal.assert_not_called()

    def test_failed_health_propagates(self):
        active=SimpleNamespace(ensure_main=Mock(),next_frame=Mock(),ocr=Mock(return_value=[]))
        with TemporaryDirectory() as directory, patch('cloud_revive.recovery_navigation',return_value=nullcontext()), patch('cloud_revive.world_heal_and_reenter',side_effect=RuntimeError('unknown HP')):
            with self.assertRaisesRegex(RuntimeError,'unknown HP'):prepare_daily_team(active,Path(directory)/'claim-pending.json')

    def test_scope_identity_and_order(self):
        tree=ast.parse((Path(__file__).parents[1]/'main_cloud_daily.py').read_text(encoding='utf-8'))
        wrapper=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='account_run')
        calls={n.func.id:n.lineno for n in ast.walk(wrapper) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertLess(calls['verify_account_identity'],calls['prepare_daily_team'])
        self.assertLess(calls['prepare_daily_team'],calls['verify_task_team'])
        gate=next(n for n in ast.walk(wrapper) if isinstance(n,ast.If) and any(isinstance(c,ast.Call) and isinstance(c.func,ast.Name) and c.func.id=='prepare_daily_team' for c in ast.walk(n)))
        self.assertEqual(ast.unparse(gate.test),"args.once_daily and (not args.daily_probe) and (args.account == 'a')")


if __name__=='__main__':unittest.main()
