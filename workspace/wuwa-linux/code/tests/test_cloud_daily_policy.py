import unittest
from cloud_daily_policy import authorize_selection, ForgeryClaimBudget, verified_inventory, verify_claim
from types import SimpleNamespace
class PolicyTests(unittest.TestCase):
    def test_tacet_entry_uses_shared_refill_only_when_enabled(self):
        import ast
        from pathlib import Path
        from unittest.mock import Mock
        tree=ast.parse((Path(__file__).resolve().parents[1]/'cloud_daily_policy.py').read_text(encoding='utf-8'))
        install=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='install')
        functions=[n for n in install.body if isinstance(n,ast.FunctionDef) and n.name in ('domain_inventory','tacet_book')]
        for browser,enabled,current,refilled in [(True,True,6,True),(True,True,66,False),(True,False,6,False),(False,True,6,False)]:
            with self.subTest(browser=browser,enabled=enabled,current=current):
                state={'current':current}
                journal=Mock(spec=['assert_clear','begin','complete'])
                original=Mock(return_value='opened')
                def refill(task,target,inventory): state['current']+=60
                ns={'original_tacet_book':original,'original_inventory':Mock(side_effect=AssertionError('Do not reopen book')),
                    'journal':journal,'verified_inventory':lambda t:(state['current'],0),'refill':refill}
                exec(compile(ast.Module(body=functions,type_ignores=[]),'policy','exec'),ns)
                task=SimpleNamespace(is_browser=lambda:browser,_cloud_allow_solvent_entry=enabled,stamina_once=60,
                    get_stamina=lambda:(state['current'],0,state['current']),log_info=Mock())
                self.assertEqual(ns['tacet_book'](task,'gray_book_boss'),'opened')
                self.assertEqual(state['current'],current+60 if refilled else current)
                self.assertEqual(journal.complete.called,refilled)
                original.assert_called_once_with(task,'gray_book_boss')
                task.get_stamina=Mock(side_effect=AssertionError('Recovery book has no stamina HUD'))
                original.reset_mock()
                self.assertEqual(ns['tacet_book'](task,'gray_book_all_monsters'),'opened')
                self.assertEqual(ns['tacet_book'](task),'opened')
                task.get_stamina.assert_not_called()

    def test_refill_panel_close_retries_and_never_confirms(self):
        from cloud_daily_policy import close_refill_panel
        from unittest.mock import Mock
        task=SimpleNamespace(ocr=Mock(return_value=[SimpleNamespace(name='补充结晶波片')]),
            sleep=Mock(),click_relative=Mock(),wait_until=Mock(side_effect=[False,True]))
        close_refill_panel(task)
        self.assertEqual(task.click_relative.call_count,2)
        for call in task.click_relative.call_args_list:
            self.assertEqual(call.args,(383/1280,520/720))

    def test_refill_panel_stuck_stops_inventory_read(self):
        from cloud_daily_policy import close_refill_panel
        from unittest.mock import Mock
        task=SimpleNamespace(ocr=Mock(return_value=[SimpleNamespace(name='补充结晶波片')]),
            sleep=Mock(),click_relative=Mock(),wait_until=Mock(return_value=False))
        with self.assertRaises(RuntimeError):close_refill_panel(task)
        self.assertEqual(task.click_relative.call_count,3)

    def test_pre_entry_refill_only_for_explicit_cloud_trial(self):
        import ast
        from pathlib import Path
        from unittest.mock import Mock
        tree=ast.parse((Path(__file__).resolve().parents[1]/'cloud_daily_policy.py').read_text(encoding='utf-8'))
        install=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='install')
        fn=next(n for n in install.body if isinstance(n,ast.FunctionDef) and n.name=='domain_inventory')
        for cloud,budget,current,expected in [(False,True,12,False),(True,False,12,False),
                                             (True,True,40,False),(True,True,12,True)]:
            state={'current':current}
            journal=Mock(spec=['assert_clear','begin','complete'])
            def refill(task,target,inventory): state['current']+=60
            ns={'original_inventory':lambda t:(current,53,current+53),'journal':journal,
                'verified_inventory':lambda t:(state['current'],53),'refill':refill}
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'policy','exec'),ns)
            task=SimpleNamespace(is_browser=lambda:cloud,stamina_once=40,log_info=Mock())
            if budget:task._cloud_forgery_budget=ForgeryClaimBudget(3)
            result=ns['domain_inventory'](task)
            self.assertEqual(result[0],current+60 if expected else current)
            self.assertEqual(journal.complete.called,expected)

    def test_result_requires_controls_and_actual_deduction_without_top_hud(self):
        for text, good in [('退出副本 重新挑战 剩余50',True),
                           ('退出副本 重新挑战 剩余130',False),
                           ('退出副本 重新挑战',False),('剩余50',False)]:
            task=SimpleNamespace(has_claim_stamina=lambda:False,
                                 ocr=lambda *args:[SimpleNamespace(name=text)],
                                 wait_until=lambda fn,**kw: self.assertEqual(fn(),good))
            verify_claim(task,130,53,80)

    def test_inventory_keeps_reserve_and_current_boxes_separate(self):
        task = SimpleNamespace(ocr=lambda *args: [SimpleNamespace(name=s) for s in ['53', '65/240']],
                               get_stamina=lambda: (65,53,118))
        self.assertEqual(verified_inventory(task),(65,53))

    def test_inventory_rejects_missing_conflicting_or_ambiguous_current(self):
        for texts in [['53'], ['64/240'], ['65/240', '65/240']]:
            task = SimpleNamespace(ocr=lambda *args: [SimpleNamespace(name=s) for s in texts],
                                   get_stamina=lambda: (65,53,118))
            with self.assertRaises(RuntimeError): verified_inventory(task)

    def test_trial_stops_after_three_verified_double_claims(self):
        budget=ForgeryClaimBudget(3)
        for expected in (True,True,False):
            budget.before_claim(40)
            self.assertEqual(budget.verified(80),(expected,80))
        with self.assertRaises(RuntimeError):budget.before_claim(40)
        with self.assertRaises(RuntimeError):budget.verified(80)

    def test_trial_rejects_wrong_cost_without_progress(self):
        budget=ForgeryClaimBudget(3)
        with self.assertRaises(RuntimeError):budget.before_claim(60)
        with self.assertRaises(RuntimeError):budget.verified(120)
        self.assertEqual(budget.completed,0)

    def test_only_identified_free_materials(self):
        with self.assertRaises(RuntimeError): authorize_selection('reserve','提取等量结晶单质')
        authorize_selection('solvent','消耗1结晶溶剂补充60结晶波片')
        for kind,text in [('reserve','消耗60星声补充60结晶波片'),('solvent',''),('premium','提取等量结晶单质')]:
            with self.assertRaises(RuntimeError): authorize_selection(kind,text)
if __name__=='__main__': unittest.main()
