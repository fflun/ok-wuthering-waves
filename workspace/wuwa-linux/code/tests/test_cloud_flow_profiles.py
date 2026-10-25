from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cloud_autorun_state import DailyLedger, write_json
from cloud_flow_profiles import plan_flow
from cloud_weekly_state import WeeklyLedger

NOW = datetime(2026, 10, 12, 10, tzinfo=timezone(timedelta(hours=8)))


class FlowProfileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.daily = DailyLedger(self.root / 'daily.json')
        self.weekly = WeeklyLedger(self.root / 'weekly.json')

    def plan(self, **kwargs):
        return plan_flow(self.daily, self.weekly, now=NOW, **kwargs)

    def test_simple_retains_weekly_material_rewards_without_echo(self):
        result = self.plan()
        self.assertEqual([a['stage'] for a in result['actions']], ['daily', 'boss', 'garden'])
        self.assertEqual(result['actions'][1]['remaining_claims'], 3)
        self.assertEqual(result['actions'][1]['level'], 90)
        self.assertFalse(result['actions'][1]['absorb_echo'])

    def test_full_boss_is_twenty_echo_only_rounds(self):
        action = self.plan(mode='full', echo_target='boss')['actions'][-1]
        self.assertEqual((action['stage'], action['rounds'], action['level']), ('boss_echo', 20, 80))
        self.assertFalse(action['claim_stamina_rewards'])
        self.assertEqual(action['yolo_fallback_seconds'], 10)
        self.assertIsNone(self.plan(mode='full')['required_scheduler_seconds'])

    def test_nests_and_both_are_distinct_choices(self):
        result = self.plan(mode='full', echo_target='nests')
        self.assertEqual(result['actions'][-1]['stage'], 'nest_echo')
        self.assertNotIn('boss_echo', [a['stage'] for a in result['actions']])
        self.assertTrue(result['actions'][-1]['require_verified_absorption'])
        both = self.plan(mode='full', echo_target='both')
        self.assertEqual([a['stage'] for a in both['actions']][-2:], ['boss_echo', 'nest_echo'])

    def test_failure_blocks_echo_stages(self):
        write_json(self.weekly.path, {'2026-10-12': {'boss': {'status': 'FAILED'}}})
        result = self.plan(mode='full', echo_target='both')
        self.assertTrue(all(a['action'] == 'blocked' for a in result['actions'][-2:]))

    def test_planning_has_no_launch_or_ledger_mutation(self):
        with patch('subprocess.Popen') as launch:
            self.plan(mode='full', echo_target='both')
            launch.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_choices_are_rejected(self):
        with self.assertRaises(ValueError): self.plan(mode='unknown')
        with self.assertRaises(ValueError): self.plan(echo_target='unknown')


if __name__ == '__main__':
    unittest.main()
