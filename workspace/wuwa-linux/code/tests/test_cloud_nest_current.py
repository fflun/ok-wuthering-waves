import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from cloud_nest_current import parse_progress, Progress, install, run_native_nest, NestProgressLost,walk_verified_objective


class CurrentNestTests(unittest.TestCase):
    def test_blind_text_entry_needs_two_fresh_objectives_and_is_not_completion(self):
        from contextlib import nullcontext
        frames=['前往烬心域','清理聚落中的残象','清理聚落中的残象','清理聚落中的残象']
        task=SimpleNamespace(info={'Nest Target':'盲望之塌残象聚落'},next_frame=Mock(),log_info=Mock(),
            ocr=Mock(side_effect=[[SimpleNamespace(name=s)] for s in frames]))
        progress=Progress(task,48);progress.book_count=(0,48);reads=[]
        def native(condition,direction,**kwargs):
            self.assertEqual(direction,'w');self.assertEqual(kwargs,dict(time_out=14,running=False,target=False))
            for _ in range(3):
                value=condition();reads.append(value)
                if value:return value
        with patch('cloud_revive.recovery_navigation',return_value=nullcontext()):
            self.assertEqual(walk_verified_objective(task,progress,native),(0,48))
        self.assertEqual(reads,[False,False,(0,48)]);self.assertFalse(progress.complete)
    def test_blind_entry_absent_objective_stops_without_combat_authorization(self):
        from contextlib import nullcontext
        task=SimpleNamespace(info={'Nest Target':'盲望之塌残象聚落'},next_frame=Mock(),log_info=Mock(),ocr=Mock(return_value=[]))
        progress=Progress(task,48);progress.book_count=(0,48)
        with patch('cloud_revive.recovery_navigation',return_value=nullcontext()):
            with self.assertRaises(NestProgressLost):walk_verified_objective(task,progress,lambda condition,*a,**k:condition())
        self.assertFalse(progress.complete)
    def test_blind_entry_wrong_or_completed_book_cannot_move(self):
        native=Mock()
        for name,book in [('其他聚落',(0,48)),('盲望之塌残象聚落',(48,48))]:
            task=SimpleNamespace(info={'Nest Target':name});progress=SimpleNamespace(total=48,book_count=book)
            with self.assertRaises(RuntimeError):walk_verified_objective(task,progress,native)
        native.assert_not_called()
    def test_story_displaced_counter_still_requires_two_real_full_reads(self):
        def ocr(*rect):
            self.assertEqual(rect,(.005,.20,.29,.56))
            return [SimpleNamespace(name='前往烬心域'),SimpleNamespace(name='清剿残象聚落'),SimpleNamespace(name=next(counter))]
        counter=iter(['已击败残象：45/48','已击败残象：48/48','已击败残象：48/48'])
        task=SimpleNamespace(ocr=ocr,log_info=Mock(),info={})
        with patch('cloud_nest_current.time.monotonic',side_effect=[0,1,2,3]):
            progress=Progress(task,48);self.assertEqual(progress.read(),(45,48));self.assertFalse(progress.complete)
            progress.read();self.assertFalse(progress.complete)
            progress.read();self.assertTrue(progress.complete)
    def test_expanded_region_rejects_two_counters(self):
        task=SimpleNamespace(ocr=Mock(return_value=[SimpleNamespace(name='已击败残象：45/48 已击败残象：2/48')]),info={},log_info=Mock())
        progress=Progress(task,48);self.assertIsNone(progress.read());self.assertFalse(progress.complete)
    def test_empty_search_exits_native_without_repeating_search_or_combat(self):
        from cloud_nest_current import NestSearchCompleted
        task=SimpleNamespace(info={},combat_nest=Mock(side_effect=NestSearchCompleted()))
        reenter=Mock()
        run_native_nest(task,'same',reenter,lambda:True)
        task.combat_nest.assert_called_once();reenter.assert_not_called()
        with self.assertRaisesRegex(RuntimeError,'incomplete'):run_native_nest(task,'same',reenter,lambda:False)
    def test_objective_loss_releases_input_and_reenters_same_verified_target(self):
        complete=[False]
        task=SimpleNamespace(info={},log_info=Mock(),reset_to_false=Mock(),
            executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock())))
        def combat(target):
            if target=='initial':raise NestProgressLost('unreadable')
            complete[0]=True
        task.combat_nest=Mock(side_effect=combat)
        reenter=Mock(return_value='same_verified_target')
        run_native_nest(task,'initial',reenter,lambda:complete[0])
        self.assertEqual([c.args[0] for c in task.combat_nest.call_args_list],['initial','same_verified_target'])
        task.executor.interaction.release_all.assert_called_once()
        reenter.assert_called_once();task.reset_to_false.assert_called_once()

    def test_objective_recovery_exhaustion_stops_after_three_native_entries(self):
        task=SimpleNamespace(info={},log_info=Mock(),reset_to_false=Mock(),
            executor=SimpleNamespace(interaction=SimpleNamespace(release_all=Mock())),
            combat_nest=Mock(side_effect=NestProgressLost('unreadable')))
        reenter=Mock(return_value='same')
        with self.assertRaisesRegex(RuntimeError,'recovery retry limit'):
            run_native_nest(task,'initial',reenter,lambda:False)
        self.assertEqual(task.combat_nest.call_count,3)
        self.assertEqual(reenter.call_count,2)

    def test_other_combat_error_cannot_authorize_objective_reentry(self):
        task=SimpleNamespace(info={},combat_nest=Mock(side_effect=RuntimeError('unknown error')))
        reenter=Mock()
        with self.assertRaisesRegex(RuntimeError,'unknown error'):
            run_native_nest(task,'initial',reenter,lambda:False)
        reenter.assert_not_called()

    def test_live_clear_nest_label_retains_only_verified_incomplete_baseline(self):
        task=SimpleNamespace(ocr=Mock(return_value=[SimpleNamespace(name='清剿残象聚落')]),info={},log_info=Mock())
        progress=Progress(task,48);progress.book_count=(0,48)
        self.assertEqual(progress.read(),(0,48));self.assertFalse(progress.complete)
        self.assertEqual(progress.full_reads,0)

    def test_clear_nest_label_without_book_proof_cannot_authorize_progress(self):
        task=SimpleNamespace(ocr=Mock(return_value=[SimpleNamespace(name='清剿残象聚落')]))
        self.assertIsNone(Progress(task,48).read())

    def test_clear_nest_label_cannot_confirm_full_or_other_nest_total(self):
        for baseline in ((48,48),(0,41)):
            task=SimpleNamespace(ocr=Mock(return_value=[SimpleNamespace(name='清剿残象聚落')]))
            progress=Progress(task,48);progress.book_count=baseline
            self.assertIsNone(progress.read());self.assertFalse(progress.complete)

    def test_text_objective_retains_verified_incomplete_count_without_victory(self):
        task=SimpleNamespace(ocr=Mock(return_value=[SimpleNamespace(name='清理聚落中的残象')]),info={},log_info=Mock())
        with patch('cloud_nest_current.time.monotonic',side_effect=[0,1,2,185]):
            progress=Progress(task,48)
            progress.book_count=(0,48)
            self.assertEqual(progress.read(),(0,48))
            self.assertEqual(progress.read(),(0,48))
            self.assertFalse(progress.complete)
            with self.assertRaisesRegex(RuntimeError,'no verified progress'):
                progress.read()

    def test_text_objective_without_book_proof_does_not_invent_progress(self):
        task=SimpleNamespace(ocr=Mock(return_value=[SimpleNamespace(name='清理聚落中的残象')]))
        progress=Progress(task,48)
        self.assertIsNone(progress.read())

    def test_active_text_cannot_second_confirm_a_full_counter(self):
        task=SimpleNamespace(ocr=Mock(side_effect=[[SimpleNamespace(name=t)] for t in ('已击败残象：48/48','清理聚落中的残象')]),info={},log_info=Mock())
        with patch('cloud_nest_current.time.monotonic',side_effect=[0,1,2]):
            progress=Progress(task,48)
            progress.book_count=(0,48)
            progress.read();progress.read()
            self.assertFalse(progress.complete)
            self.assertEqual(progress.full_reads,0)

    def test_native_revive_reenters_verified_same_nest(self):
        complete=[False]
        task=SimpleNamespace(info={},log_info=Mock())
        def combat(target):
            if target=='initial':task.info['Revive']='Success'
            else:complete[0]=True
        task.combat_nest=Mock(side_effect=combat)
        reenter=Mock(return_value='verified_same_nest')
        run_native_nest(task,'initial',reenter,lambda:complete[0])
        reenter.assert_called_once_with()
        self.assertEqual([c.args[0] for c in task.combat_nest.call_args_list],['initial','verified_same_nest'])

    def test_stale_revive_flag_cannot_authorize_return(self):
        task=SimpleNamespace(info={'Revive':'Success'},log_info=Mock(),combat_nest=Mock())
        reenter=Mock()
        with self.assertRaisesRegex(RuntimeError,'without verified revival'):
            run_native_nest(task,'initial',reenter,lambda:False)
        reenter.assert_not_called()

    def test_repeated_revive_stops_after_three_attempts(self):
        task=SimpleNamespace(info={},log_info=Mock())
        task.combat_nest=Mock(side_effect=lambda _:task.info.update(Revive='Success'))
        reenter=Mock(return_value='same')
        with self.assertRaisesRegex(RuntimeError,'retry limit'):
            run_native_nest(task,'same',reenter,lambda:False)
        self.assertEqual(task.combat_nest.call_count,3)
        self.assertEqual(reenter.call_count,2)

    def test_initial_nest_without_counter_uses_native_enemy_detection(self):
        from pathlib import Path
        for native_result in (True,False):
            task=SimpleNamespace(**{name:Mock() for name in (
                'in_combat','combat_end_condition','combat_once','find_f_with_text',
                'pick_f','pick_echo','walk_find_echo')})
            original=task.in_combat
            original.return_value=native_result
            task.ocr=Mock(return_value=[SimpleNamespace(name='清理聚落中的残象')])
            task.run_until=Mock()
            install(task,Path('.'))
            hook=next(c.cell_contents for c in task.run.__closure__
                      if callable(c.cell_contents) and getattr(c.cell_contents,'__name__','')=='in_combat')
            self.assertIs(hook(),native_result)
            original.assert_called_once_with()

    def test_selected_total_uses_same_completion_rule(self):
        self.assertEqual(parse_progress('已击败残象：6/48',48),(6,48))
        self.assertEqual(parse_progress('残象聚落已清剿',48),(48,48))
        self.assertEqual(parse_progress('残象聚落已清理 等待明日刷新',48),(48,48))
        self.assertIsNone(parse_progress('已击败残象：41/41',48))

    def test_reject_wrong_or_ambiguous_progress(self):
        self.assertEqual(parse_progress('已击败残象：3/41'),(3,41))
        self.assertEqual(parse_progress('已击败残像：41/41'),(41,41))
        for text in ('3/41','已击败残象：42/41','已击败残象：0/24','已击败残象：3/41 已击败残象：4/41'):
            self.assertIsNone(parse_progress(text))

    def test_two_separate_full_reads_required(self):
        task=SimpleNamespace(ocr=Mock(side_effect=[[SimpleNamespace(name=f'已击败残象：{n}/41')] for n in (40,41,41)]),info={},log_info=Mock())
        with patch('cloud_nest_current.time.monotonic',side_effect=[0,1,2,3]):
            progress=Progress(task)
            progress.read(); self.assertFalse(progress.complete)
            progress.read(); self.assertFalse(progress.complete)
            progress.read(); self.assertTrue(progress.complete)

    def test_missing_does_not_mean_victory(self):
        task=SimpleNamespace(ocr=Mock(side_effect=[[SimpleNamespace(name='已击败残象：3/41')],[],[]]),info={},log_info=Mock())
        with patch('cloud_nest_current.time.monotonic',side_effect=[0,1,2,18]):
            progress=Progress(task);progress.read();progress.read()
            self.assertFalse(progress.complete)
            with self.assertRaisesRegex(RuntimeError,'unreadable'):progress.read()

    def test_full_count_can_transition_to_explicit_cleared_label(self):
        task=SimpleNamespace(ocr=Mock(side_effect=[[SimpleNamespace(name=s)] for s in ('已击败残象：41/41','残象聚落已清剿 明日刷新')]),info={},log_info=Mock())
        with patch('cloud_nest_current.time.monotonic',side_effect=[0,1,2]):
            progress=Progress(task);progress.read()
            self.assertFalse(progress.complete)
            progress.read();self.assertTrue(progress.complete)
