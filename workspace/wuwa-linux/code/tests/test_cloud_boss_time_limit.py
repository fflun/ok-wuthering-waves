import ast
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main_cloud_daily import task_time_limit


class BossTimeLimitTests(unittest.TestCase):
    def args(self, **changes):
        values=dict(account='a',task='echo',once_daily=False,forgery_rounds=None,
                    weekly_probe=False,weekly_rounds=None)
        values.update(changes)
        return SimpleNamespace(**values)

    def test_queue_matches_parent_bound(self):
        launcher=Path(__file__).resolve().parents[3]/'outputs/run_a_all_boss_20261008.py'
        tree=ast.parse(launcher.read_text(encoding='utf8'))
        child=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='child')
        call=next(n for n in ast.walk(child) if isinstance(n,ast.Call)
                  and isinstance(n.func,ast.Name) and n.func.id=='main')
        self.assertTrue(any(k.arg=='boss_batch' and k.value.value is True for k in call.keywords))
        self.assertEqual(task_time_limit(self.args(),boss_batch=True),3000)
        self.assertIn('time.monotonic()-started>3000',launcher.read_text(encoding='utf8'))

    def test_other_tasks_keep_original_limits(self):
        with patch.dict(os.environ,{},clear=True):
            for task,limit in [('echo',1200),('garden',1800),('nightmare',1200),('forgery',1200)]:
                self.assertEqual(task_time_limit(self.args(task=task)),limit)
        with patch.dict(os.environ,{'OKWW_FULL_RUN_ID':'owned'}):
            for task in ('echo','nightmare'):
                self.assertEqual(task_time_limit(self.args(task=task)),2700)
            self.assertEqual(task_time_limit(self.args(task='garden')),1800)

    def test_claims_and_other_accounts_cannot_get_boss_limit(self):
        for changes in [dict(account='b'),dict(account='c'),dict(task='nightmare'),
                        dict(once_daily=True),dict(forgery_rounds=1),
                        dict(weekly_probe=True),dict(weekly_rounds=1)]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                task_time_limit(self.args(**changes),boss_batch=True)

    def test_main_deadline_and_error_use_same_bound(self):
        source=Path(__file__).resolve().parents[1]/'main_cloud_daily.py'
        tree=ast.parse(source.read_text(encoding='utf8'))
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        statements=[n for n in ast.walk(main) if isinstance(n,ast.Assign)]
        limit=next(n for n in statements if any(isinstance(t,ast.Name) and t.id=='time_limit' for t in n.targets))
        deadline=next(n for n in statements if any(isinstance(t,ast.Name) and t.id=='deadline' for t in n.targets)
                      and isinstance(n.value,ast.BinOp) and isinstance(n.value.right,ast.Name))
        namespace=dict(task_time_limit=task_time_limit,args=self.args(),boss_batch=True,
                       time=SimpleNamespace(monotonic=lambda:100))
        for statement in (limit,deadline):
            module=ast.fix_missing_locations(ast.Module(body=[statement],type_ignores=[]))
            exec(compile(module,str(source),'exec'),namespace)
        self.assertEqual(namespace['deadline'],3100)
        self.assertIn('Task exceeded {time_limit//60} minute limit',source.read_text(encoding='utf8'))


if __name__=='__main__':unittest.main()
