import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from cloud_daily_death_watch import guarded_heavy,install

class Revived(Exception):pass

class DeathWatchTests(unittest.TestCase):
    def task(self):
        return SimpleNamespace(is_browser=lambda:True,_in_combat=True,next_frame=Mock(),sleep=Mock(),
            executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock())),
            raise_not_in_combat=Mock(side_effect=Revived),log_info=Mock())
    def test_two_fresh_popup_frames_release_input_before_native_recovery(self):
        task=self.task();native=Mock();char=SimpleNamespace(task=task)
        with patch('cloud_revive.popup',side_effect=[True,True]):
            with self.assertRaises(Revived):guarded_heavy(char,native)
        self.assertEqual(task.next_frame.call_count,2)
        task.executor.interaction.release_all.assert_called_once()
        task.raise_not_in_combat.assert_called_once();native.assert_not_called()
    def test_normal_or_flickering_popup_keeps_native_return_and_arguments(self):
        for observations in ([False],[True,False]):
            task=self.task();native=Mock(return_value='native-result')
            with patch('cloud_revive.popup',side_effect=observations):
                self.assertEqual(guarded_heavy(SimpleNamespace(task=task),native,1,x=2),'native-result')
            native.assert_called_once_with(1,x=2);task.raise_not_in_combat.assert_not_called()
    def test_nonbrowser_or_noncombat_never_checks_popup(self):
        for browser,combat in ((False,True),(True,False)):
            task=self.task();task.is_browser=lambda:browser;task._in_combat=combat
            with patch('cloud_revive.popup') as popup:
                self.assertEqual(guarded_heavy(SimpleNamespace(task=task),lambda:7),7)
                popup.assert_not_called()
    def test_install_is_scoped_to_aemeath_and_not_duplicated_after_load(self):
        char=type('Aemeath',(),{})();char.heavy_wait_highlight_down=Mock(return_value=9)
        other=SimpleNamespace(heavy_wait_highlight_down=Mock())
        material=SimpleNamespace(chars=[char,other,None],load_chars=Mock(return_value=8))
        install(material);self.assertEqual(material.load_chars(),8)
        first=char.heavy_wait_highlight_down
        material.load_chars();install(material)
        self.assertIs(char.heavy_wait_highlight_down,first)
        self.assertFalse(hasattr(other,'_cloud_heavy_death_watch'))

if __name__=='__main__':unittest.main()
