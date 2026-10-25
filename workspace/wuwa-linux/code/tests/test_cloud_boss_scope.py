import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from cloud_echo_progress import EchoProgress
from cloud_all_boss import positive_victory,active_instance_objective

class BossScopeTests(unittest.TestCase):
    def test_loading_identity_wait_keeps_inputs_blocked_until_verified(self):
        from cloud_all_boss import wait_account_ready
        from types import SimpleNamespace
        from unittest.mock import Mock
        timer=[0];capture=SimpleNamespace(block_input=False)
        task=SimpleNamespace(executor=SimpleNamespace(method=capture),log_info=Mock(),sleep=lambda n:timer.__setitem__(0,timer[0]+n))
        read=Mock(side_effect=[RuntimeError('Game account identifier unreadable; no nest action'),'synthetic'])
        def verify(value):
            self.assertTrue(capture.block_input);self.assertEqual(value,'synthetic')
        snap=Mock()
        self.assertEqual(wait_account_ready(task,read,verify,snap,clock=lambda:timer[0]),'synthetic')
        self.assertFalse(capture.block_input);snap.assert_called_once_with('identity-wait')
    def test_identity_timeout_and_mismatch_remain_blocked(self):
        from cloud_all_boss import wait_account_ready
        from types import SimpleNamespace
        from unittest.mock import Mock
        for mismatch in [False,True]:
            timer=[0];capture=SimpleNamespace(block_input=False)
            task=SimpleNamespace(executor=SimpleNamespace(method=capture),log_info=Mock(),sleep=lambda n:timer.__setitem__(0,timer[0]+n))
            read=Mock(return_value='wrong') if mismatch else Mock(side_effect=RuntimeError('Game account identifier unreadable; no nest action'))
            verify=Mock(side_effect=ValueError('wrong account'))
            with self.assertRaises((RuntimeError,ValueError)):
                wait_account_ready(task,read,verify,Mock(),timeout=3,clock=lambda:timer[0])
            self.assertTrue(capture.block_input)
            if mismatch:self.assertEqual(read.call_count,1)
            else:verify.assert_not_called()
    def test_pending_pickup_rejects_real_enemies_but_not_absorption_animation(self):
        from cloud_all_boss import pickup_has_enemies
        from types import SimpleNamespace
        for hp,text,expected in [(True,'',True),(False,'击败敌人',True),
                                 (False,'领取奖励',False),(False,'',False)]:
            task=SimpleNamespace(check_health_bar=lambda:hp,
                ocr=lambda *args:[SimpleNamespace(name=text)] if text else [])
            self.assertEqual(pickup_has_enemies(task),expected)
    def test_launcher_resume_history_remains_serializable_and_does_not_alias_previous(self):
        import importlib.util,json
        path=Path(__file__).resolve().parents[3]/'outputs/run_a_all_boss_20261008.py'
        spec=importlib.util.spec_from_file_location('all_boss_launcher',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        old=dict(status='FAILED',completed=1,attempts=[])
        history=module.prior_attempts(old)
        self.assertEqual(len(json.loads(json.dumps(history))),1)
        self.assertEqual(old['attempts'],[])
        newer=dict(status='FAILED',completed=2,attempts=history)
        self.assertEqual(len(module.prior_attempts(newer)),2)
    def test_normal_boss_challenge_active_objective_keeps_instance_protection(self):
        self.assertTrue(active_instance_objective('击败敌人'))
        self.assertTrue(active_instance_objective('擊敗敵人'))
        self.assertFalse(active_instance_objective('领取奖励'))
        self.assertFalse(active_instance_objective(''))
    def test_no_victory_from_empty_screen_or_old_reward_alone(self):
        valid=dict(seen=True,team=True,enemies=False,active=False,recovery=False,reward=True)
        self.assertTrue(positive_victory(**valid))
        for field,value in [('seen',False),('team',False),('enemies',True),('active',True),('recovery',True),('reward',False)]:
            with self.subTest(field=field):
                self.assertFalse(positive_victory(**dict(valid,**{field:value})))
    def test_other_boss_cannot_reuse_first_boss_or_other_account_progress(self):
        with tempfile.TemporaryDirectory() as folder,patch('cloud_echo_progress.day_key',return_value='2026-10-08'):
            path=Path(folder)/'boss.json'
            progress=EchoProgress(path,'123456789','2026-10-08','qiangdi:无常凶鹭')
            progress.victory('owner','victory.png');progress.pickup_finished(False,'pickup.png')
            self.assertEqual(EchoProgress(path,'123456789','2026-10-08','qiangdi:无常凶鹭').completed,1)
            for account,target in [('123456789','weekly-list-1-level-80'),('987654321','qiangdi:无常凶鹭'),('123456789','qiangdi:飞廉之猩')]:
                with self.assertRaises(RuntimeError):EchoProgress(path,account,'2026-10-08',target)
    def test_pending_victory_blocks_next_round_and_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            progress=EchoProgress(Path(folder)/'boss.json','123456789','2026-10-08','qiangdi:test')
            with patch('cloud_echo_progress.day_key',return_value='2026-10-08'):
                progress.victory('owner','victory.png')
                with self.assertRaises(RuntimeError):progress.victory('owner','second.png')
            with patch('cloud_echo_progress.day_key',return_value='2026-10-09'):
                with self.assertRaises(RuntimeError):progress.pickup_finished(True,'pickup.png')

if __name__=='__main__':unittest.main()
