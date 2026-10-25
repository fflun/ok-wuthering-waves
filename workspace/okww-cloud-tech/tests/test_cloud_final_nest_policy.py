import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from cloud_autorun_state import write_json
from cloud_final_nest_policy import collect_final_skip,validate_final_skip,OTHER_NESTS,OPTIONAL_PICKUP_TARGET,POLICY,SKIPPED
from cloud_full_chain import FullLedger
from cloud_small_account_chain import run_tail

DAY='2026-10-15';NOW=datetime(2026,10,15,2,tzinfo=timezone.utc).timestamp()
class FinalNestSkipTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.state=self.root/'state';self.out=self.root/'owned';self.out.mkdir();self.state.mkdir()
        write_json(self.state/'accounts/registry.json',dict(accounts=[dict(id='a',expected_uid_hash='identity')]))
        for i,(name,total) in enumerate(OTHER_NESTS.items()):
            write_json(self.state/f'nest-state-{i}.json',dict(day=DAY,account='identity',target=name,total=total,phase='PICKED_UP',verified_count=[total,total],book_count=[total,total]))
        self.final=self.state/'nest-state-final.json'
        write_json(self.final,dict(day=DAY,account='identity',target=OPTIONAL_PICKUP_TARGET,total=24,phase='IN_PROGRESS',book_count=[2,24]))
        self.native=self.state/'nightmare-result.json'
        write_json(self.native,dict(status='FAILED',run_id='owned',retry_allowed=True,at=NOW))
        self.events=[dict(event='selected',name=OPTIONAL_PICKUP_TARGET,count=[n,24]) for n in [0,0,2]]
        self.events.append(dict(event='batch_failed',error='Same-nest objective recovery retry limit reached',at=NOW,image='failure.png'))
        (self.out/'failure.png').write_bytes(b'evidence')
        self.save_events()
    def save_events(self):
        (self.out/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in self.events),encoding='utf-8')
    def collect(self,config=None):
        with patch('cloud_final_nest_policy.day_key',return_value=DAY):
            return collect_final_skip(DAY,'owned',self.out,self.state,config if config is not None else dict(final_nest_failure_policy=POLICY))
    def test_exhausted_final_is_skipped_without_fabricating_completion(self):
        receipt=self.collect();self.assertEqual(receipt['status'],SKIPPED)
        self.assertFalse(receipt['catalog_complete']);self.assertEqual(receipt['last_verified_count'],[2,24])
        self.assertEqual(json.loads(self.native.read_text())['status'],'FAILED')
        self.assertEqual(json.loads(self.final.read_text())['phase'],'IN_PROGRESS')
    def test_policy_off_or_different_target_or_other_error_cannot_skip(self):
        self.assertIsNone(self.collect({}))
        self.events[-2]['name']='其他聚落';self.save_events();self.assertIsNone(self.collect())
        self.events[-2]['name']=OPTIONAL_PICKUP_TARGET;self.events[-1]['error']='unknown resource';self.save_events();self.assertIsNone(self.collect())
    def test_fewer_than_three_final_entries_cannot_skip(self):
        self.events.pop(0);self.save_events();self.assertIsNone(self.collect())
    def test_stale_unowned_or_user_stopped_cannot_skip(self):
        for changed in [dict(status='FAILED',run_id='another',retry_allowed=True,at=NOW),dict(status='FAILED',run_id='owned',retry_allowed=False,at=NOW)]:
            write_json(self.native,changed)
            with self.assertRaises(RuntimeError):self.collect()
    def test_pending_resources_and_stop_still_block(self):
        for path in [self.state/'stop-request',self.state.parent/'claim-pending.json']:
            path.write_text('{}')
            with self.assertRaises(RuntimeError):self.collect()
            path.unlink()
    def test_other_unfinished_nest_cannot_be_covered_by_final_skip(self):
        r=json.loads((self.state/'nest-state-0.json').read_text());r['phase']='IN_PROGRESS';write_json(self.state/'nest-state-0.json',r)
        with self.assertRaises(RuntimeError):self.collect()
    def test_preserve_failed_history_and_continue_c_before_b(self):
        receipt=self.collect();ledger=FullLedger(self.state/'full-ledger.json')
        write_json(ledger.path,{DAY:dict(nest_echo=dict(status='FAILED',run_id='owned',started_at=NOW-100,attempt_count=2,history=[]))})
        ledger.accept_failed_final_skip(DAY,receipt)
        record=ledger.read()[DAY]['nest_echo'];self.assertEqual(record['status'],SKIPPED);self.assertEqual(record['history'][-1]['status'],'FAILED')
        self.assertFalse(ledger.begin(DAY,'nest_echo','new',NOW+1))
        result=dict(mode='full',status='SUCCEEDED_WITH_SKIPS',day=DAY,allowed_skips=[receipt]);calls=[]
        with patch('cloud_small_account_chain.day_key',return_value=DAY):
            completed=run_tail(result,self.state,lambda a,o:(calls.append(a) or dict(status='SUCCEEDED',run_id=o)),lambda a:None)
        self.assertEqual(calls,['c','b']);self.assertEqual(completed['status'],'SUCCEEDED_WITH_SKIPS')
    def test_skip_cannot_fake_full_success_or_cover_wrong_stage(self):
        receipt=self.collect();receipt['catalog_complete']=True
        with self.assertRaises(RuntimeError):validate_final_skip(receipt)
        with patch('cloud_small_account_chain.day_key',return_value=DAY):
            with self.assertRaises(RuntimeError):run_tail(dict(mode='full',status='SUCCEEDED_WITH_SKIPS',day=DAY),self.state,lambda *a:self.fail('started'),lambda a:None)

if __name__=='__main__':unittest.main()
