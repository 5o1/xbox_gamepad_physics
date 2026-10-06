import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_cad_reference import audit


class CadReferenceTests(unittest.TestCase):
    def test_no_execution_and_changed_literal_or_hash_rejected(self):
        raw=b"SIZE = 0.1\nraise RuntimeError('must never execute')\n"
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'part.py').write_bytes(raw)
            item={'file':'part.py','sha256':hashlib.sha256(raw).hexdigest(),'constants':{'SIZE':.1}}
            self.assertFalse(audit({'files':[item]},folder)['target_parameters_adopted'])
            with self.assertRaises(ValueError):
                audit({'files':[{**item,'constants':{'SIZE':.2}}]},folder)
            with self.assertRaises(ValueError):
                audit({'files':[{**item,'sha256':'incorrect'}]},folder)

    def test_missing_parameter_is_not_defaulted(self):
        raw=b"OTHER = 0.1\n"
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'part.py').write_bytes(raw)
            with self.assertRaises(ValueError):
                audit({'files':[{'file':'part.py','sha256':hashlib.sha256(raw).hexdigest(),'constants':{'SIZE':0}}]},folder)
