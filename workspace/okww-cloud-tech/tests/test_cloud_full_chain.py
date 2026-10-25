from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from cloud_autorun_state import DailyLedger, write_json
from cloud_weekly_state import WeeklyLedger
from cloud_full_chain import FullLedger, run_full_chain, assert_full_ready, execute_echo_stage

NOW = datetime(2026, 10, 5, 10, tzinfo=timezone(timedelta(hours=8)))


class FullChainTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / 'work/code'; self.root.mkdir(parents=True)
        self.state = self.root.parent / 'session/background'; self.state.mkdir(parents=True)
        self.daily = DailyLedger(self.state / 'daily-ledger.json')
        self.weekly = WeeklyLedger(self.state / 'weekly-ledger.json')
        self.full = FullLedger(self.state / 'full-ledger.json')
        write_json(self.daily.path, {'2026-10-05': {'status': 'SUCCEEDED'}})
        write_json(self.weekly.path, {'2026-10-05': {'boss': {'status': 'SUCCEEDED'}, 'garden': {'status': 'SUCCEEDED'}}})
        self.calls = []; self.notices = []

    def echo(self, stage, day, owner, timeout):
        self.calls.append(stage)
        return dict(status='SUCCEEDED', run_id=owner, game_day=day,
                    completed_at=NOW.timestamp()+1, combats_completed=20, catalog_complete=True)

    def run_flow(self, **kwargs):
        return run_full_chain(self.daily, self.weekly, self.full,
            Mock(side_effect=AssertionError('completed base must not rerun')), kwargs.pop('echo', self.echo),
            now=lambda: NOW, notify=lambda s,e:self.notices.append(s), **kwargs)

    def test_twenty_boss_then_all_nests_and_same_day_skip(self):
        self.assertEqual(self.run_flow()['completed_stages'], ['boss_echo','nest_echo'])
        self.assertEqual(self.calls, ['boss_echo','nest_echo'])
        self.assertEqual(self.run_flow()['status'], 'SKIPPED')
        self.assertEqual(len(self.calls), 2)

    def test_boss_failure_stops_nests_and_notifies_once(self):
        def failure(*args): raise RuntimeError('boss failed')
        with self.assertRaisesRegex(RuntimeError, 'boss failed'): self.run_flow(echo=failure)
        self.assertEqual(self.notices, ['boss_echo'])
        self.assertEqual(self.full.read()['2026-10-05']['boss_echo']['status'], 'FAILED')
        with self.assertRaisesRegex(RuntimeError, 'needs review'): self.run_flow()
        self.assertEqual(self.calls, [])

    def test_nest_failure_preserves_successful_boss(self):
        def execute(stage,*args):
            if stage == 'nest_echo': raise RuntimeError('pickup not confirmed')
            return self.echo(stage,*args)
        with self.assertRaisesRegex(RuntimeError, 'pickup not confirmed'): self.run_flow(echo=execute)
        self.assertEqual(self.full.read()['2026-10-05']['boss_echo']['status'], 'SUCCEEDED')
        self.assertEqual(self.full.read()['2026-10-05']['nest_echo']['status'], 'FAILED')

    def test_optional_final_failure_continues_without_an_outer_retry(self):
        from cloud_final_nest_policy import SKIPPED,POLICY,OTHER_NESTS,OPTIONAL_PICKUP_TARGET
        def execute(stage,day,owner,timeout):
            receipt=self.echo(stage,day,owner,timeout)
            if stage=='nest_echo':
                receipt.update(status=SKIPPED,policy=POLICY,source='owned_failure_with_user_authorized_final_skip',
                    skipped_targets=[OPTIONAL_PICKUP_TARGET],recovery_attempts=3,
                    failure_reason='Same-nest objective recovery retry limit reached',catalog_complete=False,
                    stamina_claims=0,catalog={**{n:[t,t] for n,t in OTHER_NESTS.items()},OPTIONAL_PICKUP_TARGET:[2,24]})
            return receipt
        result=self.run_flow(echo=execute,stage_retries=1)
        self.assertEqual(self.calls,['boss_echo','nest_echo'])
        self.assertEqual(result['status'],'SUCCEEDED_WITH_SKIPS')
        self.assertEqual(self.full.read()['2026-10-05']['nest_echo']['status'],SKIPPED)
        self.assertNotIn('nest_echo',result['completed_stages']);self.assertEqual(self.notices,[])
        again=self.run_flow(echo=execute,stage_retries=1)
        self.assertEqual(again['status'],'SUCCEEDED_WITH_SKIPS')
        self.assertEqual(self.calls,['boss_echo','nest_echo'])

    def test_nineteen_fights_is_not_completion(self):
        def short(*args): return dict(self.echo(*args), combats_completed=19)
        with self.assertRaisesRegex(RuntimeError, 'twenty'): self.run_flow(echo=short)
        self.assertNotIn('nest_echo', self.calls)

    def test_interrupted_run_blocks_before_any_base_action(self):
        write_json(self.full.path, {'2026-10-04': {'boss_echo': {'status':'RUNNING'}}})
        with self.assertRaisesRegex(RuntimeError, 'Interrupted'): self.run_flow()
        self.assertEqual(self.calls, [])

    def test_refresh_during_echo_stops_and_preserves_failed_receipt(self):
        times = iter([NOW, NOW, NOW, NOW, NOW, NOW + timedelta(days=1)])
        with self.assertRaisesRegex(RuntimeError, 'refreshed'):
            run_full_chain(self.daily,self.weekly,self.full,Mock(),self.echo,now=lambda:next(times))

    def test_live_gate_and_scheduler_gate_are_required(self):
        with self.assertRaisesRegex(RuntimeError, 'live acceptance'): assert_full_ready({}, {})
        with self.assertRaisesRegex(RuntimeError, 'three-hour'):
            assert_full_ready({'full_chain_live_verified':True,'weekly_chain_live_verified':True}, {})

    def test_owned_boss_child_requires_all_twenty_victory_events(self):
        config=dict(python='mock-python',browser_deps=str(self.root),runtime=str(self.root))
        def child(command, **kwargs):
            self.assertNotIn('OKWW_WEEKLY_LEDGER', kwargs['env'])
            out=Path(command[-1])
            events=[dict(event='combat_returned',round=i) for i in range(1,21)]
            events.append(dict(event='batch_succeeded',at=NOW.timestamp()+1,combats=20))
            (out/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events),encoding='utf-8')
            write_json(self.state/'echo-result.json',dict(status='SUCCEEDED',run_id='owner'))
            return Mock(returncode=0)
        with patch('subprocess.Popen',side_effect=child):
            result=execute_echo_stage('boss_echo','2026-10-05','owner',2700,config,self.root,self.state)
        self.assertEqual(result['combats_completed'],20)
        self.assertEqual(result['stamina_claims'],0)

    def test_trial_requires_explicit_switch_offline_evidence_and_scheduler(self):
        config=dict(full_trial_enabled=True,full_scheduler_timeout_seconds=10800)
        with self.assertRaisesRegex(RuntimeError,'live acceptance'):assert_full_ready({},config)
        assert_full_ready({'full_chain_offline_verified':True},config)
        with self.assertRaisesRegex(RuntimeError,'three-hour'):
            assert_full_ready({'full_chain_offline_verified':True},{'full_trial_enabled':True})


if __name__=='__main__': unittest.main()
