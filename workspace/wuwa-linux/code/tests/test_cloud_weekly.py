import unittest
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock,patch
from cloud_weekly_trial import weekly_dialog,exit_result,install_probe,weekly_in_combat,restart_result,material_combat

class WeeklyTests(unittest.TestCase):
    def run_material_loop(self, fail_claim=False, revived=False):
        completed=[False]
        entries=[]
        task=SimpleNamespace(config={},info={},wait_feature=Mock(),click_team_challenge=Mock(),
            has_claim_stamina=Mock(return_value=False),in_combat=Mock(return_value=True),
            combat_end_condition=Mock(return_value=False),pick_echo=Mock(),walk_find_echo=Mock(),
            sleep=Mock(),reset_to_false=Mock(return_value=False),walk_to_treasure=Mock(),
            pick_f=Mock(),load_chars=Mock(),frame=None)
        def native():
            self.assertTrue(task._cloud_use_revive_medicine)
            self.assertEqual(task._cloud_revive_entry_config['Boss Level'],'90')
            entries.append(task.config['Teleport to Boss'])
            completed[0]=True
        task.do_run=native
        def ocr(*args,**kwargs):
            pattern=kwargs.get('match')
            return [object()] if pattern and '领取奖励' in pattern.pattern and completed[0] else []
        task.ocr=ocr
        task.wait_until=lambda condition,**kwargs:condition()
        def claim(task,output,number):
            if fail_claim:raise RuntimeError('claim not verified')
            task.info['Weekly Verified Claims']=number
        def restart(task):completed[0]=False
        standin=SimpleNamespace(WWOneTimeTask=SimpleNamespace(run=lambda task:None))
        with tempfile.TemporaryDirectory() as directory,patch.dict(sys.modules,{'src.task.WWOneTimeTask':standin,'cv2':Mock()}), \
             patch('cloud_weekly_trial.weekly_dialog',return_value=False), \
             patch('cloud_weekly_trial.claim_weekly',side_effect=claim) as claims, \
             patch('cloud_weekly_trial.restart_result',side_effect=restart) as restarts, \
             patch('cloud_weekly_trial.exit_result') as exits, \
             patch('cloud_revive.recover_before_entry',side_effect=[revived,False,False]), \
             patch('cloud_weekly_recovery.recovery',side_effect=lambda task:nullcontext()):
            install_probe(task,Path(directory),3)
            if fail_claim:
                with self.assertRaisesRegex(RuntimeError,'claim not verified'):task.run()
            else:task.run()
            self.assertFalse(hasattr(task,'_cloud_use_revive_medicine'))
            return entries,claims.call_count,restarts.call_count,exits.call_count

    def test_three_claim_loop_restarts_twice_and_exits_only_at_end(self):
        self.assertEqual(self.run_material_loop(),(['Weekly Challenge','No','No'],3,2,1))

    def test_recovered_first_challenge_continues_without_another_teleport(self):
        self.assertEqual(self.run_material_loop(revived=True),(['No','No','No'],3,2,1))

    def test_unverified_claim_stops_before_restart_or_next_combat(self):
        self.assertEqual(self.run_material_loop(fail_claim=True),(['Weekly Challenge'],1,0,0))

    def test_verified_result_restarts_without_exit_or_claim_click(self):
        button=object()
        task=SimpleNamespace(ocr=Mock(side_effect=[[object()],[button]]),click_box=Mock(),
                             wait_until=Mock(return_value=False),
                             wait_in_team_and_world=Mock())
        restart_result(task)
        task.click_box.assert_called_once_with(button,after_sleep=2)
        task.wait_in_team_and_world.assert_called_once_with(time_out=120)

    def test_restart_rejects_failed_or_ambiguous_result_before_input(self):
        for reads in ([[]],[[object()],[]],[[object()],[object(),object()]]):
            task=SimpleNamespace(ocr=Mock(side_effect=reads),click_box=Mock())
            with self.assertRaises(RuntimeError):restart_result(task)
            task.click_box.assert_not_called()

    def test_material_run_keeps_entry_and_skips_echo_actions(self):
        pick,walk=Mock(),Mock()
        task=SimpleNamespace(pick_echo=pick,walk_find_echo=walk,
                             config={'Teleport to Boss':'Weekly Challenge'},_just_entered_boss_realm=False)
        def native():
            self.assertEqual(task.config['Teleport to Boss'],'Weekly Challenge')
            self.assertFalse(task.pick_echo())
            self.assertFalse(task.walk_find_echo())
            return 'native combat returned'
        self.assertEqual(material_combat(task,native),'native combat returned')
        pick.assert_not_called();walk.assert_not_called()
        self.assertIs(task.pick_echo,pick);self.assertIs(task.walk_find_echo,walk)

    def test_restarted_round_bypasses_teleport_and_restores_on_failure(self):
        pick,walk=Mock(),Mock()
        task=SimpleNamespace(pick_echo=pick,walk_find_echo=walk,
                             config={'Teleport to Boss':'Weekly Challenge'},_just_entered_boss_realm=False)
        def native():
            self.assertEqual(task.config['Teleport to Boss'],'No')
            self.assertTrue(task._just_entered_boss_realm)
            raise RuntimeError('combat failed')
        with self.assertRaisesRegex(RuntimeError,'combat failed'):material_combat(task,native,restarted=True)
        self.assertEqual(task.config['Teleport to Boss'],'Weekly Challenge')
        self.assertFalse(task._just_entered_boss_realm)
        self.assertIs(task.pick_echo,pick);self.assertIs(task.walk_find_echo,walk)

    def test_victory_latch_prevents_phantom_reentry_during_loot(self):
        task=SimpleNamespace(_cloud_weekly_victory=False,
            combat_end_condition=Mock(side_effect=[True,False]),reset_to_false=Mock(return_value=False))
        native=Mock(return_value=True)
        self.assertFalse(weekly_in_combat(task,native))
        self.assertFalse(weekly_in_combat(task,native))
        native.assert_not_called()
        task._cloud_weekly_victory=False
        self.assertTrue(weekly_in_combat(task,native))
        native.assert_called_once()

    def test_weekly_requires_explicit_sixty_cost(self):
        for text,expected in [('领取奖励需消耗60点结晶波片，请确认是否领取？',True),
                              ('领取奖励需消耗120点结晶波片',False),
                              ('结晶波片不足，是否继续进入',False),
                              ('领取奖励需消耗60星声',False)]:
            task=SimpleNamespace(ocr=lambda *a:[SimpleNamespace(name=text)])
            self.assertEqual(weekly_dialog(task),expected)

    def test_result_exit_requires_unique_control(self):
        for count in (0,2):
            task=SimpleNamespace(ocr=lambda *a,**k:[object()]*count,click_box=Mock())
            with self.assertRaises(RuntimeError):exit_result(task)
            task.click_box.assert_not_called()

    def test_reject_more_than_three_before_installing(self):
        with self.assertRaises(ValueError):install_probe(None,None,4)
