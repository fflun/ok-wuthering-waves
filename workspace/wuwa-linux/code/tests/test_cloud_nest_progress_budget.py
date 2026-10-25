import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from cloud_nest_current import Progress,combat_until_verified,NestProgressLost

class BudgetTests(unittest.TestCase):
    def fixture(self,counts,seconds=30):
        clock=[0.0]; counts=iter(counts)
        task=SimpleNamespace(info={},log_info=Mock(),executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock())))
        task.sleep=lambda n:clock.__setitem__(0,clock[0]+n)
        current=[None]
        task.ocr=lambda *a:[SimpleNamespace(name=current[0])] if current[0] else []
        def native(*a,**k):
            clock[0]+=seconds
            n=next(counts)
            current[0]=None if n is None else f'已击败残象：{n}/48'
            return 'native_result'
        task.native=Mock(side_effect=native)
        return task,clock
    def test_saved_42_of_48_continues_past_four_returns_and_two_full_frames(self):
        task,clock=self.fixture([42,43,44,45,46,47,48,48])
        with patch('cloud_nest_current.time.monotonic',side_effect=lambda:clock[0]):
            progress=Progress(task,48)
            self.assertEqual(combat_until_verified(task,progress,task.native,target=True),'native_result')
        self.assertTrue(progress.complete);self.assertEqual(task.native.call_count,8)
        self.assertEqual(task.executor.interaction.release_all.call_count,7)
        self.assertTrue(all(c.kwargs=={'target':True} for c in task.native.call_args_list))
    def test_no_progress_retains_180_second_stop_without_victory(self):
        task,clock=self.fixture([42]*10,60)
        with patch('cloud_nest_current.time.monotonic',side_effect=lambda:clock[0]):
            progress=Progress(task,48)
            with self.assertRaisesRegex(RuntimeError,'no verified progress'):
                combat_until_verified(task,progress,task.native)
        self.assertFalse(progress.complete);self.assertLess(task.native.call_count,10)
    def test_ongoing_increments_still_have_absolute_900_second_bound(self):
        task,clock=self.fixture(range(1,40),100)
        with patch('cloud_nest_current.time.monotonic',side_effect=lambda:clock[0]):
            progress=Progress(task,48)
            with self.assertRaisesRegex(RuntimeError,'900 second'):
                combat_until_verified(task,progress,task.native)
        self.assertFalse(progress.complete);self.assertEqual(task.native.call_count,9)
    def test_missing_initial_counter_cannot_allow_loot(self):
        task,clock=self.fixture([None])
        with patch('cloud_nest_current.time.monotonic',side_effect=lambda:clock[0]):
            progress=Progress(task,48)
            with self.assertRaises(NestProgressLost):combat_until_verified(task,progress,task.native)
        self.assertFalse(progress.complete)
    def test_native_revive_or_other_error_is_not_swallowed(self):
        task,clock=self.fixture([1])
        task.native.side_effect=ValueError('native_failure')
        with patch('cloud_nest_current.time.monotonic',side_effect=lambda:clock[0]):
            progress=Progress(task,48)
            with self.assertRaisesRegex(ValueError,'native_failure'):
                combat_until_verified(task,progress,task.native)
        task.native.assert_called_once()
    def test_already_verified_completion_never_restarts_combat(self):
        task,clock=self.fixture([1])
        progress=SimpleNamespace(complete=True)
        self.assertIsNone(combat_until_verified(task,progress,task.native))
        task.native.assert_not_called()
