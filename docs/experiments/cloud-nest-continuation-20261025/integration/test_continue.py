import hashlib,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from cloud_nest_state import NestState,pending_hint,game_day,CLEARED_NEST_CONTINUATION_POLICY,UNCONFIRMED_PHASE
from cloud_nest_pickup import PickupNotConfirmed,PickupTargetNotReached,PickupSearchEmpty
from cloud_full_chain import collect_echo_receipt,FullLedger
from stage_policy import run_plan
from tests.test_cloud_nest_pickup import PickupTests

class ContinueTests(unittest.TestCase):
    def test_full_flow_thirty_second_search_deadline(self):
        for seconds in (30,90):
            task,pickup,_=PickupTests().make();task._cloud_nest_pickup_seconds=seconds
            with patch('cloud_nest_pickup.time.monotonic',side_effect=[0,seconds+1,seconds+1]):
                with self.assertRaisesRegex(RuntimeError,'bounded search'):pickup.collect()
            task.send_key.assert_not_called();pickup._detect.assert_not_called()

    def proof(self,folder,name,total):
        image=Path(folder)/'proof.png';image.write_bytes(b'fixture')
        return dict(target=name,count=[total,total],absorb_sent=False,bounded_search_completed=True,
                    user_policy=CLEARED_NEST_CONTINUATION_POLICY,image=str(image),
                    image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())

    def test_all_supported_nests_continue_without_fake_absorption(self):
        for total in (24,36,41,48):
            with self.subTest(total=total),tempfile.TemporaryDirectory() as f:
                name='测试残象聚落';p=Path(f)/'nest-state-a.json'
                state=NestState(p,'a',target=name,key='key',total=total)
                state.reconcile(name,(total,total),(total,total))
                for sent in (False,True):
                    # Each scenario starts from its own verified completion.
                    state.record['phase']='CLEARED_PENDING_PICKUP'
                    state.continue_after_search(dict(self.proof(f,name,total),absorb_sent=sent))
                    self.assertEqual(state.record['phase'],UNCONFIRMED_PHASE)
                    self.assertIs(state.record['absorbed'],False)
                    self.assertIsNone(pending_hint(f,'a'))
                    self.assertEqual(NestState(p,'a',target=name,key='key',total=total)
                        .reconcile(name,(total,total),(total,total)),UNCONFIRMED_PHASE)

    def test_incomplete_unknown_target_or_changed_evidence_still_stop(self):
        with tempfile.TemporaryDirectory() as f:
            name='测试残象聚落';state=NestState(Path(f)/'state.json','a',target=name,key='x',total=48)
            proof=self.proof(f,name,48)
            state.reconcile(name,(47,48),(47,48))
            with self.assertRaises(RuntimeError):state.continue_after_search(proof)
            state.reconcile(name,(48,48),(48,48))
            for changes in ({'target':'other'},{'count':[47,48]}, {'user_policy':'wrong'},
                            {'bounded_search_completed':False},{'image_sha256':'bad'}, {'absorb_sent':None}):
                with self.assertRaises(RuntimeError):state.continue_after_search(dict(proof,**changes))

    def task_run(self,folder,*,enabled,changed=False,search_error=None):
        from cloud_nest_current import install
        task,_,finder=PickupTests().make()
        for method in ('in_combat','combat_end_condition','combat_once','pick_f','pick_echo','walk_find_echo','run_until'):
            setattr(task,method,Mock())
        task.find_f_with_text=finder;task.info={};task.ensure_main=Mock();task.load_chars=Mock()
        task.reset_to_false=Mock();task.click=Mock();task.width_of_screen=lambda f:1280*f
        task._travel_to_nest_or_skip=Mock(return_value=True)
        task.run_in_circle_to_find_echo=Mock()
        task.in_team=lambda:(True,0,3)
        task.frame=np.zeros((720,1280,3),dtype=np.uint8)
        task._cloud_nest_continue_unconfirmed=enabled
        name='梦枢天罗残象聚落';box=SimpleNamespace(name='48/48',x=680,y=350,width=40,height=20)
        selections=[0]
        def select(*args):
            selections[0]+=1
            title='other' if changed and selections[0]>1 else name
            return box,'key',title,(48,48),(48,48)
        stub=SimpleNamespace(WWOneTimeTask=SimpleNamespace(run=Mock()))
        def fail_search(search):
            error=search_error or PickupTargetNotReached('fixture search exhausted')
            if isinstance(error,PickupTargetNotReached):search.target_seen=True
            elif not isinstance(error,PickupSearchEmpty):search.absorb_sent=True
            raise error
        with patch.dict('sys.modules',{'src.task.WWOneTimeTask':stub,
            'src.task.NightmareNestTask':SimpleNamespace(NestTarget=lambda box,key:SimpleNamespace(box=box,cache_key=key))}), \
            patch('cloud_nest_current.read_account',return_value='123456789'), \
            patch('cloud_nest_entry.select',side_effect=select), \
            patch('cloud_nest_current.NestState',side_effect=lambda path,account,**kw:NestState(Path(folder)/'state.json',account,**kw)), \
            patch('cloud_nest_pickup.NestPickup._search',new=fail_search):
            install(task,Path(folder))
            task.run()
        return task,json.loads((Path(folder)/'state.json').read_text())

    def test_real_callback_finishes_search_and_releases_pending(self):
        with tempfile.TemporaryDirectory() as f:
            task,receipt=self.task_run(f,enabled=True)
            self.assertTrue(task.info['Nest Echo Search Completed'])
            self.assertFalse(task.info['Nest Echo Collected'])
            self.assertTrue(task.info['Nest Pickup Unconfirmed Allowed'])
            self.assertEqual(receipt['phase'],UNCONFIRMED_PHASE)
            task.run_in_circle_to_find_echo.assert_called_once_with(circle_count=1)
            self.assertIsNone(pending_hint(f,'123456789'))

    def test_sent_f_without_notification_can_continue_but_not_claim_absorption(self):
        with tempfile.TemporaryDirectory() as f:
            task,receipt=self.task_run(f,enabled=True,search_error=PickupNotConfirmed('F notification missing'))
            self.assertFalse(task.info['Nest Echo Collected'])
            self.assertEqual(receipt['absorption_status'],'UNCONFIRMED')

    def test_no_target_and_no_world_objective_uses_verified_book_completion(self):
        with tempfile.TemporaryDirectory() as f:
            task,receipt=self.task_run(f,enabled=True,search_error=PickupSearchEmpty('no target found'))
            self.assertFalse(receipt['pickup_search']['absorb_sent'])
            self.assertFalse(task.info['Nest Echo Collected'])
            self.assertTrue(task.info['Nest Echo Search Completed'])

    def test_changed_identity_and_strict_other_callers_still_stop(self):
        for enabled,changed in ((True,True),(False,False)):
            with tempfile.TemporaryDirectory() as f:
                with self.assertRaises(RuntimeError):self.task_run(f,enabled=enabled,changed=changed)

    def test_receipt_lists_unconfirmed_separately_and_summary_reports_skips(self):
        with tempfile.TemporaryDirectory() as f:
            folder=Path(f);day=game_day();run='owned'
            names=['测试一残象聚落','测试二残象聚落']
            results={names[0]:dict(search_completed=True,absorbed=False,unconfirmed_allowed=True,
                                 continuation_policy=CLEARED_NEST_CONTINUATION_POLICY),
                     names[1]:dict(search_completed=True,absorbed=True,unconfirmed_allowed=False)}
            (folder/'events.jsonl').write_text(json.dumps(dict(at=time.time(),event='batch_succeeded',
                catalog={n:[48,48] for n in names},finished=names,pickup_results=results)))
            (folder/'nightmare-result.json').write_text(json.dumps(dict(status='SUCCEEDED',run_id=run)))
            receipt=collect_echo_receipt('nest_echo',day,run,folder,folder)
            self.assertEqual(receipt['verified_pickups'],[names[1]])
            self.assertEqual(receipt['pickup_unconfirmed_allowed'],[names[0]])
            ledger=FullLedger(folder/'full.json');ledger.begin(day,'nest_echo',run,time.time()-10)
            ledger.finish(day,'nest_echo',run,receipt)
            record=ledger.read()[day]['nest_echo']
            summary=run_plan([('nest_echo',False,lambda:record)],lambda:None,lambda r:None)
            self.assertEqual(summary['status'],'SUCCEEDED_WITH_SKIPS')

if __name__=='__main__':unittest.main()
