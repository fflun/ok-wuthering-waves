import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from cloud_echo_progress import resume_scene


class BossResumeTests(unittest.TestCase):
    def task(self,title='Lv.80 天演溯心·衍律化形',goal='领取奖励'):
        def ocr(*rect,**kwargs):
            if rect==(.30,0,.72,.075):return [SimpleNamespace(name=title)]
            pattern=kwargs['match']
            return [SimpleNamespace(name=goal)] if pattern.search(goal) else []
        return SimpleNamespace(next_frame=Mock(),ocr=ocr,in_team=lambda:(True,0,3))
    def test_pending_victory_is_preserved_before_navigation(self):
        task=self.task();self.assertEqual(resume_scene(task,pending=True),'victory')
        task.next_frame.assert_called_once()
    def test_pending_never_reenters_or_replays_an_active_boss(self):
        for title,goal in [('Lv.80 天演溯心·衍律化形','击败敌人'),('Lv.90 天演溯心·衍律化形','领取奖励')]:
            with self.assertRaisesRegex(RuntimeError,'no navigation sent'):
                resume_scene(self.task(title,goal),pending=True)
    def test_existing_active_boss_can_resume_native_combat(self):
        self.assertEqual(resume_scene(self.task(goal='击败敌人')),'active')
    def test_world_and_other_boss_are_not_current_target(self):
        self.assertIsNone(resume_scene(self.task(title='',goal='')))
        self.assertIsNone(resume_scene(self.task(title='Lv.90 天演溯心',goal='击败敌人')))
    def test_saved_victory_does_not_require_a_disappeared_boss_title(self):
        self.assertEqual(resume_scene(self.task(title='',goal='领取奖励'),pending=True),'victory')
    def test_reconnect_without_objective_allows_search_not_new_victory(self):
        self.assertEqual(resume_scene(self.task(title='',goal=''),pending=True),'pending_search_only')
    def test_missing_team_does_not_authorize_pending_search(self):
        task=self.task(title='',goal='');task.in_team=lambda:(False,-1,0)
        with self.assertRaisesRegex(RuntimeError,'no navigation sent'):resume_scene(task,pending=True)
