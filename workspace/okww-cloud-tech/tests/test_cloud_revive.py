import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cloud_revive import (hp_value, medicine_description, use_medicine,
                          medicine_or_heal, world_heal_and_reenter,
                          revive_policy, recover_before_entry, dungeon_exit_context)


def boxes(*texts):return [SimpleNamespace(name=text) for text in texts]


class ReviveTests(unittest.TestCase):
    def test_preflight_waits_world_hud_before_any_escape(self):
        task=self.task();task.dialog=False;task.world=False;task.hp='20000/20000'
        calls=[]
        def wait(predicate,**kwargs):
            calls.append(kwargs['time_out'])
            if len(calls)==1:
                self.assertFalse(predicate());task.world=True
            return predicate()
        task.wait_until=wait
        world_heal_and_reenter(task,reenter=False)
        self.assertEqual([c.args[0] for c in task.send_key.call_args_list],['1','2','3'])
        self.assertEqual(calls,[8,2,2,2])
        task.revive_at_tower_and_heal.assert_not_called()

    def test_preflight_closes_only_positive_terminal_then_verifies_world(self):
        task=self.task();task.dialog=False;task.world=False;task.hp='20000/20000'
        original_ocr=task.ocr;original_key=task.send_key.side_effect
        task.ocr=lambda *a,**k:boxes('终端','共鸣者','编队') if a==(.02,.02,.90,.60) else original_ocr(*a,**k)
        def key(value,**kwargs):
            if value=='esc':task.world=True
            else:original_key(value,**kwargs)
        task.send_key.side_effect=key
        world_heal_and_reenter(task,reenter=False)
        self.assertEqual([c.args[0] for c in task.send_key.call_args_list],['esc','1','2','3'])
        task.click_box.assert_not_called()
        task.revive_at_tower_and_heal.assert_not_called()

    def test_full_pair_retries_transient_second_frame_within_same_window(self):
        task=self.task();task.dialog=False;task.world=True
        reads=iter([(15672,15672)]*2+[(17130,17130)]*2+
                   [(25040,25040),(25040,250410)]+[(25040,25040)]*2)
        waits=[]
        def bounded(predicate,**kwargs):
            waits.append(kwargs['time_out'])
            return any(predicate() for _ in range(4))
        task.wait_until=bounded
        with patch('cloud_revive.health',side_effect=lambda t:next(reads)):
            world_heal_and_reenter(task,reenter=False)
        self.assertEqual(waits,[8,2,2,2])
        task.revive_at_tower_and_heal.assert_not_called()
        task.teleport_to_configured_boss_and_prepare.assert_not_called()

    def test_full_pair_never_accepts_isolated_full_readings(self):
        task=self.task();task.dialog=False;task.world=True
        reads=iter([(25040,25040),(25040,250410)]*30)
        task.wait_until=lambda predicate,**kwargs:any(predicate() for _ in range(4))
        with patch('cloud_revive.health',side_effect=lambda t:next(reads)):
            with self.assertRaisesRegex(RuntimeError,'not confirmed fully healed'):
                world_heal_and_reenter(task,reenter=False)
        task.revive_at_tower_and_heal.assert_called_once()
        task.teleport_to_configured_boss_and_prepare.assert_not_called()

    def test_health_recovers_real_slash_misread_without_guessing_separator(self):
        import numpy as np
        from cloud_revive import health
        task=SimpleNamespace(frame=np.zeros((720,1280,3),dtype=np.uint8))
        task.ocr=Mock(side_effect=[boxes('15672715672'),boxes('15672/15672','Lv.90')])
        self.assertEqual(health(task),(15672,15672))
        self.assertEqual(task.ocr.call_args_list[1].kwargs['frame'].shape,(2160,3840,3))

    def test_health_does_not_infer_full_health_from_digits_or_conflicting_pairs(self):
        import numpy as np
        from cloud_revive import health
        task=SimpleNamespace(frame=np.zeros((720,1280,3),dtype=np.uint8))
        task.ocr=Mock(side_effect=[boxes('15672715672'),boxes('15672715672'),boxes('15672/15672','500/15672'),boxes('15672715672'),boxes('15672715672')])
        self.assertIsNone(health(task))

    def test_health_keeps_wide_fallback_when_tight3x_has_no_pair(self):
        import numpy as np
        from cloud_revive import health
        task=SimpleNamespace(frame=np.zeros((720,1280,3),dtype=np.uint8))
        task.ocr=Mock(side_effect=[boxes('1567215672'),boxes('15672715672'),boxes('15672715672'),boxes('15672/15672')])
        self.assertEqual(health(task),(15672,15672))
        self.assertEqual(task.ocr.call_args.args,(.40,.93,.65,.99))

    def test_recovery_navigation_disables_checks_and_restores_even_on_failure(self):
        from cloud_revive import recovery_navigation
        task=self.task();task.skip_combat_check=False
        with self.assertRaisesRegex(RuntimeError,'synthetic'):
            with recovery_navigation(task):
                self.assertTrue(task.skip_combat_check)
                raise RuntimeError('synthetic')
        self.assertFalse(task.skip_combat_check)
    def test_death_fallback_runs_without_combat_sleep_checks(self):
        task=self.task();task.skip_combat_check=False
        with patch('cloud_revive.use_medicine',return_value=False),patch('cloud_revive.world_heal_and_reenter') as heal:
            heal.side_effect=lambda t:self.assertTrue(t.skip_combat_check)
            self.assertEqual(medicine_or_heal(task),'world')
        self.assertFalse(task.skip_combat_check)
    def test_normal_named_boss_can_reenter_after_full_healing(self):
        task=self.task();task.dialog=False;task.world=True;task.hp='20000/20000'
        task.config['Teleport to Boss']='Boss Challenge'
        world_heal_and_reenter(task)
        task.teleport_to_configured_boss_and_prepare.assert_called_once()
    def test_health_only_preflight_leaves_entry_to_native_wrapped_flow(self):
        task=self.task();task.dialog=False;task.world=True;task.hp='20000/20000'
        world_heal_and_reenter(task,reenter=False)
        task.revive_at_tower_and_heal.assert_not_called()
        task.teleport_to_configured_boss_and_prepare.assert_not_called()
        self.assertEqual([c.args[0] for c in task.send_key.call_args_list],['1','2','3'])
        self.assertTrue(task.world)

    def test_already_full_team_does_not_repeat_healing_teleport(self):
        task=self.task();task.dialog=False;task.world=True;task.hp='20000/20000'
        world_heal_and_reenter(task)
        task.revive_at_tower_and_heal.assert_not_called()
        task.teleport_to_configured_boss_and_prepare.assert_called_once()
        self.assertEqual([c.args[0] for c in task.send_key.call_args_list],['1','2','3'])

    def test_short_exit_requires_restart_and_confirm_not_generic_confirmation(self):
        self.assertTrue(dungeon_exit_context(boxes('确认离开','重新挑战','确认')))
        for texts in (('确认离开','确认'),('确认','领取奖励'),('购买','确认')):
            self.assertFalse(dungeon_exit_context(boxes(*texts)))

    def task(self):
        task=SimpleNamespace(dialog=True,world=False,slot=0,medicine=True,
            quantity='2',hp='5000/20000',description='恢复意识并回复5000点生命值',
            config={'Teleport to Boss':'Weekly Challenge','Which Weekly Boss to Teleport':1,'Boss Level':'80'})
        task.executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock()))
        task.next_frame=Mock();task.sleep=Mock();task.log_info=Mock()
        task.click_relative=Mock()
        task.reset_to_false=Mock();task.load_chars=Mock()
        task.in_team=lambda:(True,task.slot,3)
        task.in_world=lambda:task.world
        task.wait_until=lambda predicate,**kwargs:predicate()
        def key(value,**kwargs):
            if value in ('1','2','3'):task.slot=int(value)-1
        task.send_key=Mock(side_effect=key)
        def ocr(*args,**kwargs):
            pattern=kwargs.get('match')
            if pattern and '选择复苏' in pattern.pattern:return boxes('选择复苏物品') if task.dialog else []
            if pattern and pattern.pattern==r'^\d+$':return boxes(task.quantity)
            if pattern and pattern.pattern=='^确认$|^確認$':return boxes('确认')
            if args==(.23,.53,.77,.62):return boxes(task.description)
            if args==(.40,.93,.65,.99):return boxes(task.hp)
            if args==(.18,.25,.86,.82):return boxes('确认退出当前挑战？')
            if args==(.50,.50,.86,.80):return boxes('确认')
            return []
        task.ocr=ocr
        def click(box,**kwargs):
            if task.dialog:
                if task.medicine:task.dialog=False
            else:task.world=True
        task.click_box=Mock(side_effect=click)
        task.close_revive_popup=Mock(side_effect=lambda:setattr(task,'dialog',False))
        task.revive_at_tower_and_heal=Mock(side_effect=lambda:setattr(task,'hp','20000/20000'))
        task.teleport_to_configured_boss_and_prepare=Mock(side_effect=lambda:setattr(task,'world',False))
        return task

    def test_hp_requires_unambiguous_valid_pair(self):
        for texts,expected in [(boxes('123/999'),(123,999)),(boxes('0/999'),(0,999)),
                               (boxes('123/999','123/999'),(123,999)),
                               (boxes('123/999','4/888'),None),(boxes('999/123'),None),
                               (boxes('0/0'),None),(boxes('已复苏'),None)]:
            self.assertEqual(hp_value(texts),expected)

    def test_only_ordinary_revive_description_is_accepted(self):
        self.assertTrue(medicine_description(boxes('可使指定共鸣者恢复意识并回复5000点生命值')))
        for text in ('回复生命值','消耗结晶波片恢复意识并回复生命值',
                     '消耗星声恢复意识并回复生命值','购买月相恢复意识并回复生命值'):
            self.assertFalse(medicine_description(boxes(text)))

    def test_medicine_confirmed_once_and_verified_alive(self):
        task=self.task()
        self.assertTrue(use_medicine(task,2))
        task.click_relative.assert_called_once_with(.597,.415,after_sleep=.4)
        task.click_box.assert_called_once()
        task.send_key.assert_called_once_with('3',after_sleep=.5)
        task.revive_at_tower_and_heal.assert_not_called()

    def test_no_quantity_no_input(self):
        task=self.task();task.quantity='0'
        self.assertFalse(use_medicine(task))
        task.click_relative.assert_not_called();task.click_box.assert_not_called()

    def test_invalid_description_prevents_confirm(self):
        task=self.task();task.description='消耗星声恢复意识并回复生命值'
        self.assertFalse(use_medicine(task));task.click_box.assert_not_called()

    def test_ambiguous_confirm_never_clicks(self):
        task=self.task();original=task.ocr
        task.ocr=lambda *a,**k:boxes('确认','确认') if a==(.59,.68,.81,.75) else original(*a,**k)
        self.assertFalse(use_medicine(task));task.click_box.assert_not_called()

    def test_cooldown_never_double_confirms(self):
        task=self.task();task.medicine=False
        self.assertFalse(use_medicine(task));task.click_box.assert_called_once()

    def test_closed_popup_without_living_hp_is_not_success(self):
        for hp in ('0/20000','不可读'):
            task=self.task();task.hp=hp
            self.assertFalse(use_medicine(task));task.click_box.assert_called_once()

    def test_known_dead_slot_must_be_the_verified_active_slot(self):
        task=self.task();task.send_key.side_effect=None
        self.assertFalse(use_medicine(task,2))

    def test_success_does_not_trigger_world_fallback(self):
        task=self.task()
        with patch('cloud_revive.world_heal_and_reenter') as world:
            self.assertEqual(medicine_or_heal(task),'medicine')
            world.assert_not_called()

    def test_failed_medicine_falls_back_once_then_stops(self):
        task=self.task()
        with patch('cloud_revive.use_medicine',return_value=False),patch('cloud_revive.world_heal_and_reenter') as world:
            self.assertEqual(medicine_or_heal(task),'world')
            with self.assertRaisesRegex(RuntimeError,'already used'):medicine_or_heal(task)
            world.assert_called_once()

    def test_repeated_medicine_use_has_an_upper_bound(self):
        task=self.task()
        with patch('cloud_revive.use_medicine',return_value=True) as use,patch('cloud_revive.world_heal_and_reenter') as world:
            self.assertEqual([medicine_or_heal(task) for _ in range(3)],['medicine']*3)
            self.assertEqual(medicine_or_heal(task),'world')
            with self.assertRaisesRegex(RuntimeError,'already used'):medicine_or_heal(task)
        self.assertEqual(use.call_count,3);world.assert_called_once()

    def test_manual_stop_does_not_trigger_fallback(self):
        task=self.task()
        with patch('cloud_revive.use_medicine',side_effect=RuntimeError('task disabled')),patch('cloud_revive.world_heal_and_reenter') as world:
            with self.assertRaisesRegex(RuntimeError,'disabled'):medicine_or_heal(task)
            world.assert_not_called()

    def test_world_fallback_verifies_exit_and_all_three_slots_before_same_entry(self):
        task=self.task();order=[]
        def enter():
            order.append((task.config.copy(),task.send_key.call_args_list[-3:]))
            task.world=False
        task.teleport_to_configured_boss_and_prepare.side_effect=enter
        with revive_policy(task,dict(task.config)):
            # Native restart changes this while retaining the original target.
            task.config['Teleport to Boss']='No'
            world_heal_and_reenter(task)
        task.close_revive_popup.assert_called_once()
        task.revive_at_tower_and_heal.assert_called_once()
        task.teleport_to_configured_boss_and_prepare.assert_called_once()
        self.assertEqual(order[0][0]['Teleport to Boss'],'Weekly Challenge')
        self.assertEqual(order[0][0]['Boss Level'],'80')
        self.assertEqual([c.args[0] for c in order[0][1]],['1','2','3'])
        self.assertEqual(task.config['Teleport to Boss'],'No')

    def test_exit_without_positive_context_never_clicks_confirm(self):
        task=self.task();task.dialog=False;original=task.ocr
        task.ocr=lambda *a,**k:boxes('是否领取奖励？') if a==(.18,.25,.86,.82) else original(*a,**k)
        with self.assertRaisesRegex(RuntimeError,'exit is not positively'):world_heal_and_reenter(task)
        task.click_box.assert_not_called();task.revive_at_tower_and_heal.assert_not_called()

    def test_team_hud_alone_cannot_prove_exit(self):
        task=self.task();task.dialog=False;task.click_box.side_effect=None
        with self.assertRaisesRegex(RuntimeError,'not verified in the open world'):world_heal_and_reenter(task)
        task.revive_at_tower_and_heal.assert_not_called()

    def test_partial_healing_cannot_reenter(self):
        task=self.task();task.revive_at_tower_and_heal.side_effect=None
        with self.assertRaisesRegex(RuntimeError,'not confirmed fully healed'):world_heal_and_reenter(task)
        task.teleport_to_configured_boss_and_prepare.assert_not_called()

    def test_entry_and_policy_restored_even_when_reentry_fails(self):
        task=self.task();task._cloud_use_revive_medicine=False
        task.teleport_to_configured_boss_and_prepare.side_effect=RuntimeError('failed entry')
        with self.assertRaisesRegex(RuntimeError,'failed entry'),revive_policy(task,dict(task.config)):
            task.config['Teleport to Boss']='No'
            world_heal_and_reenter(task)
        self.assertEqual(task.config['Teleport to Boss'],'No')
        self.assertFalse(task._cloud_use_revive_medicine)
        self.assertFalse(hasattr(task,'_cloud_revive_entry_config'))

    def test_preflight_does_not_close_popup_before_medicine(self):
        task=self.task()
        with revive_policy(task,dict(task.config)):
            self.assertTrue(recover_before_entry(task))
        task.close_revive_popup.assert_not_called()
        self.assertTrue(task._just_entered_boss_realm)
        task.load_chars.assert_called_once()


if __name__=='__main__':unittest.main()
