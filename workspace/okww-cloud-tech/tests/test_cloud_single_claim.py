import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import cloud_daily_policy as policy

class SingleClaimTests(unittest.TestCase):
    def test_single_cost_and_refill_target(self):
        for once,current in [(40,100),(60,100),(40,5),(60,5)]:
            with self.subTest(once=once,current=current):
                task=SimpleNamespace(sleep=Mock(),has_claim_stamina=lambda:True,click_relative=Mock())
                journal=Mock(spec=policy.PendingClaim)
                with patch.object(policy,'verified_inventory',side_effect=[(current,53),(current+60,53)]), \
                     patch.object(policy,'click_single_claim') as single, \
                     patch.object(policy,'click_double_claim') as double, \
                     patch.object(policy,'verify_claim') as verify, \
                     patch.object(policy,'require_text'),patch.object(policy,'refill') as refill:
                    self.assertEqual(policy.claim(task,journal,once,multiplier=1),(False,once))
                    double.assert_not_called()
                    self.assertEqual(single.call_count,2 if current<once else 1)
                    journal.begin.assert_called_once_with(current,53,once)
                    self.assertEqual(verify.call_args.args[-1],once)
                    if current<once:self.assertEqual(refill.call_args.args[1],once)
                    else:refill.assert_not_called()
                    journal.complete.assert_called_once()

    def test_default_stays_double(self):
        task=SimpleNamespace(sleep=Mock(),has_claim_stamina=lambda:True)
        with patch.object(policy,'verified_inventory',return_value=(150,53)), \
             patch.object(policy,'click_single_claim') as single,patch.object(policy,'click_double_claim') as double, \
             patch.object(policy,'verify_claim'):
            self.assertEqual(policy.claim(task,Mock(spec=policy.PendingClaim),60),(False,120))
            single.assert_not_called();double.assert_called_once()

    def test_rejects_multiplier_before_spending(self):
        for multiplier in (0,3,True,'1'):
            task=Mock();journal=Mock(spec=policy.PendingClaim)
            with self.assertRaises(RuntimeError):policy.claim(task,journal,multiplier=multiplier)
            journal.begin.assert_not_called();task.click_box.assert_not_called()

if __name__=='__main__':unittest.main()
