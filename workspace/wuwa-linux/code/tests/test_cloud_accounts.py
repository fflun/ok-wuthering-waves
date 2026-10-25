import copy,hashlib,json,tempfile,unittest
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from pathlib import Path
from cloud_accounts import (account_paths,registry_template,validate_registry,write_initial_configuration,
                            isolation_manifest,verify_account_identity)
from cloud_autorun_state import day_key,week_key


class AccountTests(unittest.TestCase):
    def test_independent_profiles_and_records_with_shared_execution_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            paths=[account_paths(directory,k) for k in ('a','b','c')]
            for field in ('profile','state','runtime_config','pending_claim','logs'):
                self.assertEqual(len({getattr(p,field) for p in paths}),3)
            self.assertEqual(len({p.global_lock for p in paths}),1)
            self.assertEqual(paths[0].profile,Path(directory).resolve()/'game-profile')
    def test_one_accounts_completion_does_not_skip_other_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            ledgers=[account_paths(directory,k).ledgers()['daily'] for k in ('a','b','c')]
            self.assertTrue(ledgers[0].begin('2026-10-07')[0])
            ledgers[0].finish('2026-10-07','SUCCEEDED')
            self.assertFalse(ledgers[0].begin('2026-10-07')[0])
            for ledger in ledgers[1:]:self.assertTrue(ledger.begin('2026-10-07')[0])
    def test_weekly_full_food_and_pending_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            a,b=[account_paths(directory,k) for k in ('a','b')]
            a.ledgers()['weekly'].begin('2026-10-05','boss','a-run')
            a.ledgers()['full'].begin('2026-10-07','boss_echo','a-run',1)
            self.assertEqual(b.ledgers()['weekly'].read(),{})
            self.assertEqual(b.ledgers()['full'].read(),{})
            self.assertNotEqual(a.state/'food-receipt.json',b.state/'food-receipt.json')
            self.assertNotEqual(a.pending_claim,b.pending_claim)
    def test_disabled_setup_does_not_copy_or_modify_login_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);profile=root/'game-profile';profile.mkdir()
            (profile/'sentinel').write_text('existing login unchanged')
            (root/'daily-ledger.json').write_text('{}')
            registry=write_initial_configuration(root,'a'*64)
            self.assertFalse(registry['enabled'])
            self.assertEqual((profile/'sentinel').read_text(),'existing login unchanged')
            self.assertEqual((root/'daily-ledger.json').read_text(),'{}')
            self.assertFalse((root/'accounts/b/browser-profile').exists())
            with self.assertRaises(FileExistsError):write_initial_configuration(root)
    def test_reject_shared_profiles_duplicate_ids_and_live_enable(self):
        with tempfile.TemporaryDirectory() as directory:
            original=registry_template(directory,'a'*64)
            variants=[]
            r=copy.deepcopy(original);r['accounts'][1]['profile']=r['accounts'][0]['profile'];variants.append(r)
            r=copy.deepcopy(original);r['accounts'][1]['expected_uid_hash']='a'*64;variants.append(r)
            r=copy.deepcopy(original);r['enabled']=True;variants.append(r)
            r=copy.deepcopy(original);r['max_parallel']=3;variants.append(r)
            for registry in variants:
                with self.assertRaises(ValueError):validate_registry(registry,directory)
            with self.assertRaises(ValueError):account_paths(directory,'../a')
    def test_four_am_daily_and_monday_weekly_boundaries(self):
        zone=timezone(timedelta(hours=8))
        before=datetime(2026,10,12,3,59,tzinfo=zone);after=before+timedelta(minutes=1)
        self.assertEqual((day_key(before),week_key(before)),('2026-10-11','2026-10-05'))
        self.assertEqual((day_key(after),week_key(after)),('2026-10-12','2026-10-12'))
    def test_every_account_owns_its_endpoints_and_state_files(self):
        with tempfile.TemporaryDirectory() as directory:
            manifests=[isolation_manifest(directory,k) for k in ('a','b','c')]
            for name in manifests[0]['files']:
                self.assertEqual(len({m['files'][name] for m in manifests}),3,name)
            for name in ('bridge_port','viewer_port'):
                self.assertEqual(len({m['reserved_endpoints'][name] for m in manifests}),3)
            for name in ('screenshots','runtime_config','logs','profile'):
                self.assertEqual(len({m[name] for m in manifests}),3,name)
            for manifest in manifests:
                self.assertFalse(manifest['enabled'])
                self.assertFalse(manifest['browser_policy']['fallback_to_other_account'])
                self.assertEqual(manifest['reserved_endpoints']['cdp'],'owned_pipe_only')
    def test_junction_or_link_cannot_alias_account_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            registry=registry_template(directory)
            target=account_paths(directory,'b').root
            with patch.object(Path,'is_junction',lambda self:self==target):
                with self.assertRaisesRegex(ValueError,'junctions'):
                    validate_registry(registry,directory)
                with self.assertRaisesRegex(ValueError,'junctions'):
                    isolation_manifest(directory,'b')
    def test_mismatched_unbound_and_duplicate_identity_stop_without_rebinding(self):
        with tempfile.TemporaryDirectory() as directory:
            uid='123456789'
            digest=hashlib.sha256(uid.encode()).hexdigest()
            registry=registry_template(directory,digest)
            before=copy.deepcopy(registry)
            self.assertTrue(verify_account_identity(registry,'a',uid))
            for account,value in (('a','987654321'),('b',uid),('a',''),('a','12345678')):
                with self.assertRaises(ValueError):verify_account_identity(registry,account,value)
            self.assertEqual(registry,before)
            registry['accounts'][1]['expected_uid_hash']=digest
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                verify_account_identity(registry,'a',uid)

if __name__=='__main__':unittest.main()
