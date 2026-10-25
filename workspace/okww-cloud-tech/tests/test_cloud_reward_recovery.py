import io,json,os,unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock,patch
from cloud_material_combat import Evidence,settled,CombatObservationError
import cloud_reward_recovery as recovery


class RewardRecoveryTests(unittest.TestCase):
    def task(self):
        return SimpleNamespace(is_browser=lambda:True,next_frame=Mock(),log_info=Mock(),
            ocr=Mock(return_value=[object()]),executor=SimpleNamespace(interaction=Mock()))

    def test_only_exit_occlusion_without_active_signals_is_eligible(self):
        e=Evidence(team=True)
        self.assertTrue(recovery.eligible(e,True))
        self.assertFalse(recovery.eligible(e,False))
        for key,value in [('timer',True),('enemies',True),('unfinished',True),('recovery',True),('reward',True),('valid',False),('team',False)]:
            self.assertFalse(recovery.eligible(replace(e,**{key:value}),True))

    @patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic','OKWW_REWARD_DEEPSEEK':'1'})
    def test_api_rejects_unrestricted_actions(self):
        for answer in [{'action':'press_f'},{'action':'step_back','code':'x'},{'action':None}]:
            response=lambda *a,**k:io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(answer)}}]}).encode())
            with self.assertRaises(RuntimeError):recovery.choose_action({},response)
        response=lambda *a,**k:io.BytesIO(b'{"choices":[{"message":{"content":"{\\"action\\":\\"step_back\\"}"}}]}')
        self.assertEqual(recovery.choose_action({},response),'step_back')

    @patch.dict(os.environ,{'OKWW_REWARD_DEEPSEEK':'1'})
    def test_bounded_step_and_total_budget(self):
        task=self.task()
        with patch('cloud_material_combat.read_evidence',return_value=(Evidence(team=True),object())),patch.object(recovery,'choose_action',return_value='step_back') as model,patch.object(recovery.time,'sleep'):
            self.assertTrue(recovery.recover(task));self.assertTrue(recovery.recover(task));self.assertFalse(recovery.recover(task))
            self.assertEqual(model.call_count,2)
        self.assertEqual([c.args for c in task.executor.interaction.send_key_down.call_args_list],[('s',),('s',)])
        self.assertEqual(task.executor.interaction.send_key_up.call_count,2)

    def test_changed_scene_after_model_does_not_move(self):
        task=self.task()
        with patch('cloud_material_combat.read_evidence',side_effect=[(Evidence(team=True),None)]*2+[(Evidence(team=True,timer=True),None)]),patch.object(recovery,'choose_action',return_value='step_right'),patch.object(recovery.time,'sleep'):
            self.assertTrue(recovery.recover(task))
        task.executor.interaction.send_key_down.assert_not_called()

    def test_api_failure_releases_keys_and_propagates(self):
        task=self.task()
        with patch('cloud_material_combat.read_evidence',return_value=(Evidence(team=True),None)),patch.object(recovery,'choose_action',side_effect=RuntimeError('API unavailable')),patch.object(recovery.time,'sleep'):
            with self.assertRaises(RuntimeError):recovery.recover(task)
        task.executor.interaction.release_all.assert_called()
        task.executor.interaction.send_key_down.assert_not_called()

    def test_settled_rechecks_after_model_instead_of_assuming_success(self):
        task=self.task()
        with patch('cloud_material_combat.observe',side_effect=['UNKNOWN','COMPLETE']),patch('cloud_material_combat.time.monotonic',side_effect=[0,9]),patch.object(recovery,'recover',return_value=True) as recover:
            self.assertEqual(settled(task),'COMPLETE');recover.assert_called_once()
        with patch('cloud_material_combat.observe',return_value='UNKNOWN'),patch('cloud_material_combat.time.monotonic',side_effect=[0,9,10,19]),patch.object(recovery,'recover',side_effect=[True,False]):
            with self.assertRaises(CombatObservationError):settled(self.task())

if __name__=='__main__':unittest.main()
