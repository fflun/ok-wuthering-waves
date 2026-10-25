import tempfile
import unittest
from pathlib import Path
from cloud_nest_state import NestState, TARGET, pending_hint


class StateTests(unittest.TestCase):
    def test_only_final_nest_can_save_unconfirmed_and_resume_without_repickup(self):
        from cloud_nest_state import OPTIONAL_PICKUP_TARGET,UNCONFIRMED_PHASE
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'saved.png';image.write_bytes(b'saved fixture')
            proof=dict(target=OPTIONAL_PICKUP_TARGET,count=[24,24],absorb_sent=True,
                bounded_search_completed=True,user_policy='final_nest_ignore_unconfirmed_absorption',
                image=str(image),image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
            p=Path(folder)/'nest-state-last.json'
            state=NestState(p,'a','day',target=OPTIONAL_PICKUP_TARGET,key='last',total=24)
            state.reconcile(OPTIONAL_PICKUP_TARGET,(23,24),(23,24))
            with self.assertRaises(RuntimeError):state.unconfirmed_allowed(proof)
            state.reconcile(OPTIONAL_PICKUP_TARGET,(24,24),(24,24))
            state.unconfirmed_allowed(proof)
            self.assertFalse(state.record['absorbed'])
            self.assertIsNone(pending_hint(folder,'a','day'))
            self.assertEqual(NestState(p,'a','day',target=OPTIONAL_PICKUP_TARGET,key='last',total=24)
                .reconcile(OPTIONAL_PICKUP_TARGET,(24,24),(24,24)),UNCONFIRMED_PHASE)
            other=NestState(Path(folder)/'other.json','a','day')
            other.reconcile(TARGET,(41,41),(41,41))
            with self.assertRaises(RuntimeError):other.unconfirmed_allowed(proof)

    def test_searched_empty_never_becomes_absorbed_or_pending_again(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'nest-state-a.json';state=NestState(p,'a','day')
            state.reconcile(TARGET,(41,41),(41,41))
            image=Path(folder)/'saved.png';image.write_bytes(b'saved fixture')
            proof=dict(target=TARGET,count=[41,41],absorb_sent=False,stable_target_seen=False,
                native_circle_completed=True,image=str(image),image_sha256=__import__('hashlib').sha256(image.read_bytes()).hexdigest())
            for field in ('absorb_sent','stable_target_seen'):
                with self.assertRaises(RuntimeError):state.searched_empty(dict(proof,**{field:True}))
            state.searched_empty(proof)
            self.assertFalse(state.record['absorbed'])
            self.assertIsNone(pending_hint(folder,'a','day'))
            self.assertEqual(NestState(p,'a','day').reconcile(TARGET,(41,41),(41,41)),'SEARCHED_NO_ECHO')
    def test_pending_hint_is_account_and_day_scoped(self):
        with tempfile.TemporaryDirectory() as folder:
            state=NestState(Path(folder)/'nest-state-a.json','a','day')
            state.reconcile(TARGET,(41,41),(41,41))
            self.assertEqual(pending_hint(folder,'a','day')['target'],TARGET)
            self.assertIsNone(pending_hint(folder,'b','day'))
            self.assertIsNone(pending_hint(folder,'a','tomorrow'))
            state.picked()
            self.assertIsNone(pending_hint(folder,'a','day'))

    def test_restart_preserves_pending_and_confirmed(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'state.json'
            state = NestState(p, 'account', '2026-10-04')
            self.assertEqual(state.reconcile(TARGET, (3,41), (3,41)), 'IN_PROGRESS')
            state.cleared()
            resumed = NestState(p, 'account', '2026-10-04')
            self.assertEqual(resumed.reconcile(TARGET, (41,41), (41,41)), 'CLEARED_PENDING_PICKUP')
            resumed.picked()
            self.assertEqual(NestState(p,'account','2026-10-04').reconcile(TARGET,(41,41),(41,41)), 'PICKED_UP')

    def test_old_day_or_other_account_does_not_skip_new_run(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'state.json'
            old = NestState(p,'a','2026-10-04')
            old.reconcile(TARGET,(41,41),(41,41)); old.picked()
            self.assertEqual(NestState(p,'a','2026-10-05').reconcile(TARGET,(0,41),(0,41)), 'IN_PROGRESS')
            self.assertEqual(NestState(p,'b','2026-10-05').reconcile(TARGET,(4,41),(4,41)), 'IN_PROGRESS')

    def test_mismatch_refuses_and_keeps_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'state.json'
            state = NestState(p,'a','day'); state.reconcile(TARGET,(41,41),(41,41))
            before = p.read_bytes()
            for title, first, second in [('other',(41,41),(41,41)), (TARGET,(40,41),(41,41)),
                                         (TARGET,(0,41),(0,41))]:
                with self.assertRaises(RuntimeError):
                    NestState(p,'a','day').reconcile(title,first,second)
                self.assertEqual(p.read_bytes(), before)

    def test_no_unverified_success(self):
        with tempfile.TemporaryDirectory() as folder:
            state = NestState(Path(folder)/'state.json','a','day')
            with self.assertRaises(RuntimeError):state.cleared()
            with self.assertRaises(RuntimeError):state.picked()
            state.reconcile(TARGET,(3,41),(3,41))
            with self.assertRaises(RuntimeError):state.picked()
