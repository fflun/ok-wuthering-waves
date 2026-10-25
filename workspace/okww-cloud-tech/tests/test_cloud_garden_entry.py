import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from main_cloud_daily import verify_task_team


class GardenEntryTests(unittest.TestCase):
    def test_garden_without_combat_api_runs_native_after_preflight(self):
        native = Mock()
        task = SimpleNamespace(run=native)
        verify_task_team(task, 'garden', Path('unused'), 'a')
        task.run()
        native.assert_called_once_with()

    def test_garden_cannot_load_or_write_team(self):
        task = Mock()
        verify_task_team(task, 'garden', Path('unused'), 'a')
        task.load_chars.assert_not_called()

    def test_all_combat_tasks_still_require_team(self):
        for name in (None, 'echo', 'nightmare', 'tacet', 'forgery', 'simulation'):
            with self.subTest(task=name):
                task = SimpleNamespace(load_chars=Mock(), chars=[])
                with self.assertRaisesRegex(RuntimeError, 'no farming started'):
                    verify_task_team(task, name, Path('unused'), 'a')
                task.load_chars.assert_called_once_with()

    def test_base_character_rejected(self):
        task = SimpleNamespace(load_chars=Mock(), chars=[type('BaseChar', (), {})()] * 3)
        with self.assertRaises(RuntimeError):
            verify_task_team(task, 'echo', Path('unused'), 'a')

    def test_recognized_team_saved(self):
        task = SimpleNamespace(load_chars=Mock(), chars=[type(n, (), {})() for n in ('Qingxiao', 'Denia', 'Mornye')])
        with TemporaryDirectory() as directory:
            verify_task_team(task, 'echo', Path(directory), 'a')
            import json
            receipt = json.loads((Path(directory) / 'team-observation.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt, {'account': 'a', 'team': ['Qingxiao', 'Denia', 'Mornye']})

    def test_identity_wrapper_keeps_verification_before_native_run(self):
        source = Path(__file__).resolve().parents[1] / 'main_cloud_daily.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        wrapper = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'account_run')
        calls = {n.func.id: n.lineno for n in ast.walk(wrapper) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertLess(calls['read_account'], calls['verify_task_team'])
        self.assertLess(calls['verify_account_identity'], calls['verify_task_team'])
        self.assertLess(calls['verify_task_team'], calls['verified_run'])


if __name__ == '__main__':
    unittest.main()
