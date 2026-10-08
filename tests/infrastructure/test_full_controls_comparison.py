import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "compare_full_controls_backends",
    ROOT / "scripts" / "compare_full_controls_backends.py",
)
comparison = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(comparison)


class FullControlsComparisonTest(unittest.TestCase):
    def test_checked_in_comparison_is_current(self):
        checked = json.loads(
            (ROOT / "results" / "full_controls_backend_comparison.json").read_text()
        )
        self.assertEqual(checked, comparison.build())
        self.assertEqual(len(checked["channels"]), 21)
        self.assertLess(checked["maximum_endpoint_absolute_error"], 1e-6)
        self.assertTrue(checked["finite"])


if __name__ == "__main__":
    unittest.main()
