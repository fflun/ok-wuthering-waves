import os
from pathlib import Path
import subprocess
import sys
import unittest


class RuntimeContractTests(unittest.TestCase):
    def test_actual_runtime_contract_in_fresh_process(self):
        script = Path(__file__).with_name('offline_runtime_contract.py')
        result = subprocess.run([sys.executable, str(script)], cwd=script.parent.parent,
                                env=dict(os.environ), capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
