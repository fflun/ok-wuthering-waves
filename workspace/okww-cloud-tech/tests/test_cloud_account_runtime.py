import json,tempfile,unittest
from pathlib import Path
from cloud_accounts import write_initial_configuration,account_paths
from cloud_account_runtime import resolve_context,verify_or_bind

class RuntimeTests(unittest.TestCase):
    def setup_root(self,directory):
        root=Path(directory)/'code';root.mkdir()
        state=root.parent/'okww-cloud-session/background'
        write_initial_configuration(state)
        p=account_paths(state,'b');s=json.loads(p.config.read_text())
        s.update(mode='daily_only',allowed_stages=['daily'])
        s['weekly']['enabled']=False;s['echo']['enabled']=False
        p.config.write_text(json.dumps(s))
        return root,state,p,s
    def test_context_rejects_weekly_or_shared_slot(self):
        with tempfile.TemporaryDirectory() as d:
            root,state,p,s=self.setup_root(d)
            paths,_=resolve_context(root,'b')
            self.assertEqual(paths.profile,p.profile)
            self.assertNotEqual(paths.state,state)
            with self.assertRaises(ValueError):resolve_context(root,'a')
            s['weekly']['enabled']=True;p.config.write_text(json.dumps(s))
            with self.assertRaises(ValueError):resolve_context(root,'b')
    def test_binding_requires_opt_in_and_never_rebinds_wrong_or_duplicate_uid(self):
        with tempfile.TemporaryDirectory() as d:
            root,state,p,s=self.setup_root(d)
            with self.assertRaises(RuntimeError):verify_or_bind(root,'b','123456789')
            verify_or_bind(root,'b','123456789',True)
            before=(state/'accounts/registry.json').read_bytes()
            with self.assertRaises(ValueError):verify_or_bind(root,'b','987654321',True)
            with self.assertRaises(RuntimeError):verify_or_bind(root,'c','123456789',True)
            self.assertEqual(before,(state/'accounts/registry.json').read_bytes())
