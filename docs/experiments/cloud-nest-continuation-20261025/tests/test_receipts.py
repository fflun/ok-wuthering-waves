"""Standalone receipt/policy tests: stdlib only, no game or login."""
import hashlib,json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from cloud_nest_state import NestState,pending_hint,CLEARED_NEST_CONTINUATION_POLICY,UNCONFIRMED_PHASE
from stage_policy import run_plan

class ContinuationTests(unittest.TestCase):
    def fixture(self,folder,total=48):
        name='Example残象聚落';day='2026-01-05'
        state=NestState(Path(folder)/'nest-state-example.json','synthetic-account',day,target=name,key='example',total=total)
        image=Path(folder)/'evidence.bin';image.write_bytes(b'synthetic evidence, not a screenshot')
        proof=dict(target=name,count=[total,total],absorb_sent=False,bounded_search_completed=True,
            user_policy=CLEARED_NEST_CONTINUATION_POLICY,image=str(image),
            image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        return state,proof,name,day

    def test_all_supported_totals_continue_without_claiming_absorption(self):
        for total in (24,36,41,48):
            with self.subTest(total=total),tempfile.TemporaryDirectory() as folder:
                state,proof,name,day=self.fixture(folder,total)
                state.reconcile(name,(total,total),(total,total));state.continue_after_search(proof)
                self.assertEqual(state.record['phase'],UNCONFIRMED_PHASE)
                self.assertFalse(state.record['absorbed'])
                self.assertEqual(state.record['absorption_status'],'UNCONFIRMED')
                self.assertIsNone(pending_hint(folder,'synthetic-account',day))

    def test_incomplete_nest_never_uses_pickup_continuation(self):
        with tempfile.TemporaryDirectory() as folder:
            state,proof,name,day=self.fixture(folder)
            state.reconcile(name,(47,48),(47,48))
            with self.assertRaises(RuntimeError):state.continue_after_search(proof)

    def test_changed_identity_counts_or_policy_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            state,proof,name,day=self.fixture(folder);state.reconcile(name,(48,48),(48,48))
            for change in ({'target':'other'},{'count':[47,48]},{'user_policy':'wrong'},
                           {'bounded_search_completed':False},{'absorb_sent':None}):
                with self.assertRaises(RuntimeError):state.continue_after_search(dict(proof,**change))

    def test_modified_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            state,proof,name,day=self.fixture(folder);state.reconcile(name,(48,48),(48,48))
            Path(proof['image']).write_bytes(b'modified')
            with self.assertRaises(RuntimeError):state.continue_after_search(proof)

    def test_restart_does_not_repeat_completed_search(self):
        with tempfile.TemporaryDirectory() as folder:
            state,proof,name,day=self.fixture(folder);state.reconcile(name,(48,48),(48,48))
            state.continue_after_search(proof)
            resumed=NestState(state.path,'synthetic-account',day,target=name,key='example',total=48)
            self.assertEqual(resumed.reconcile(name,(48,48),(48,48)),UNCONFIRMED_PHASE)
            self.assertFalse(resumed.record['absorbed'])
            with self.assertRaises(RuntimeError):resumed.reconcile(name,(0,48),(0,48))

    def test_sent_absorb_without_notification_remains_unconfirmed(self):
        with tempfile.TemporaryDirectory() as folder:
            state,proof,name,day=self.fixture(folder);state.reconcile(name,(48,48),(48,48))
            state.continue_after_search(dict(proof,absorb_sent=True))
            self.assertFalse(state.record['absorbed'])

    def test_summary_reports_skips_and_continues_next_stage(self):
        order=[]
        def first():
            order.append('nests')
            return dict(status='SUCCEEDED',receipt={'pickup_unconfirmed_allowed':['example']})
        def second():order.append('next');return dict(status='SUCCEEDED')
        result=run_plan([('nests',False,first),('next',False,second)],lambda:None,lambda r:None)
        self.assertEqual(order,['nests','next'])
        self.assertEqual(result['status'],'SUCCEEDED_WITH_SKIPS')

if __name__=='__main__':unittest.main()
