from pathlib import Path
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch,Mock
import main_cloud_autodaily as launcher
from cloud_autorun_state import write_json
from cloud_weekly_chain import execute_stage


class StartupWeeklyTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        base=Path(self.folder.name)
        self.root=base/'work/code';self.root.mkdir(parents=True)
        self.state=base/'work/session/background';self.state.mkdir(parents=True)
        write_json(self.state/'autorun-config.json',dict(python=sys.executable,runtime=str(self.root),
            browser_deps=str(self.root),frozen_runtime=str(self.root),weekly_enabled=False))
        write_json(self.state/'notifications.json',{'local_enabled':True})
        write_json(self.state/'validation.json',dict(source_hashes={},**{k:True for k in
            ('synthetic_capture','game_capture','game_input','no_foreground_interference','native_daily_completed')}))
    def invoke(self,child):
        with patch.object(launcher,'ROOT',self.root),patch.object(launcher,'STATE',self.state), \
             patch.object(launcher,'fingerprint',return_value={}), \
             patch.object(launcher,'notification_ready',return_value=True), \
             patch.object(launcher,'day_key',return_value='2026-10-05'), \
             patch('subprocess.Popen',side_effect=child) as spawn:
            return launcher.run(),spawn
    def test_disabled_weekly_preserves_native_daily_command(self):
        def child(command,**kwargs):
            self.assertIn('--once-daily',command);self.assertNotIn('--weekly-rounds',command)
            write_json(self.state/'daily-result.json',dict(status='SUCCEEDED',completed_at=time.time()+1))
            return Mock(returncode=0)
        result,spawn=self.invoke(child)
        self.assertEqual(result['status'],'SUCCEEDED');spawn.assert_called_once()
        self.assertFalse((self.state/'weekly-ledger.json').exists())
    def test_disabled_weekly_skips_already_completed_day_without_launch(self):
        write_json(self.state/'daily-ledger.json',{'2026-10-05':{'status':'SUCCEEDED'}})
        result,spawn=self.invoke(Mock(side_effect=AssertionError('game forbidden')))
        self.assertEqual(result['status'],'SKIPPED');spawn.assert_not_called()
    def test_enabling_config_alone_cannot_bypass_live_acceptance(self):
        config=json.loads((self.state/'autorun-config.json').read_text())
        config['weekly_enabled']=True;write_json(self.state/'autorun-config.json',config)
        with self.assertRaisesRegex(RuntimeError,'live acceptance'):
            self.invoke(Mock(side_effect=AssertionError('game forbidden')))
        self.assertFalse((self.state/'daily-ledger.json').exists())
    def test_manual_validation_entry_does_not_enable_logon_weekly(self):
        result=dict(status='SUCCEEDED',day='2026-10-05',week='2026-10-05')
        with patch.object(launcher,'ROOT',self.root),patch.object(launcher,'STATE',self.state), \
             patch.object(launcher,'fingerprint',return_value={}), \
             patch.object(launcher,'notification_ready',return_value=True), \
             patch('cloud_weekly_chain.run_chain',return_value=result) as chain, \
             patch('subprocess.Popen',side_effect=AssertionError('game forbidden')):
            self.assertEqual(launcher.run(validate_weekly=True),result)
            chain.assert_called_once()
        self.assertIs(json.loads((self.state/'autorun-config.json').read_text())['weekly_enabled'],False)

    def test_full_startup_routes_both_echo_stages_with_offline_trial_gate(self):
        config=json.loads((self.state/'autorun-config.json').read_text())
        config.update(full_enabled=True,full_trial_enabled=True,full_scheduler_timeout_seconds=10800,daily_retries=1)
        write_json(self.state/'autorun-config.json',config)
        validation=json.loads((self.state/'validation.json').read_text())
        validation['full_chain_offline_verified']=True;write_json(self.state/'validation.json',validation)
        write_json(self.root.parent.parent/'configs/cloud-flow-profiles.json',{'full':{'echo_target':'both'}})
        with patch('cloud_full_chain.run_full_chain',return_value={'status':'SUCCEEDED'}) as full:
            self.invoke(Mock(side_effect=AssertionError('game forbidden')))
        self.assertEqual(full.call_args.kwargs['target'],'both')
        self.assertEqual(full.call_args.kwargs['daily_retries'],1)
        self.assertTrue(callable(full.call_args.kwargs['retry_check']))
    def test_weekly_child_receipt_and_remaining_claim_command(self):
        config=json.loads((self.state/'autorun-config.json').read_text())
        def child(command,**kwargs):
            self.assertEqual(command[-4:],['--task','echo','--weekly-rounds','2'])
            self.assertEqual(kwargs['env']['OKWW_WEEKLY_RUN_ID'],'owner')
            self.assertEqual(kwargs['env']['OKWW_WEEKLY_WEEK'],'2026-10-05')
            write_json(self.state/'echo-result.json',dict(status='SUCCEEDED',run_id='owner',
                game_week='2026-10-05',completed_at=time.time()+1,verified_weekly_claims=2))
            return Mock(returncode=0)
        with patch('subprocess.Popen',side_effect=child) as spawn:
            result=execute_stage('boss','2026-10-05','owner',2,1500,config,self.root,self.state)
        self.assertEqual(result['verified_weekly_claims'],2);spawn.assert_called_once()
    def test_stale_child_receipt_does_not_complete_stage(self):
        config=json.loads((self.state/'autorun-config.json').read_text())
        write_json(self.state/'echo-result.json',dict(status='SUCCEEDED',run_id='older',
            completed_at=time.time()+1,verified_weekly_claims=3))
        with patch('subprocess.Popen',return_value=Mock(returncode=0)),self.assertRaisesRegex(RuntimeError,'fresh'):
            execute_stage('boss','2026-10-05','owner',3,1500,config,self.root,self.state)
    def test_garden_native_return_cannot_replace_reward_verification(self):
        config=json.loads((self.state/'autorun-config.json').read_text())
        def child(*args,**kwargs):
            write_json(self.state/'garden-result.json',dict(status='SUCCEEDED',run_id='owner',completed_at=time.time()+1))
            write_json(self.state/'garden-state.json',dict(status='SUCCEEDED',run_id='older',
                completed_at=time.time()+1,current=6000,target=6000,verified_rewards=6))
            return Mock(returncode=0)
        with patch('subprocess.Popen',side_effect=child),self.assertRaisesRegex(RuntimeError,'stale'):
            execute_stage('garden','2026-10-05','owner',0,2100,config,self.root,self.state)


if __name__=='__main__':unittest.main()
