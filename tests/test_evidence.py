import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
module = importlib.util.spec_from_file_location(
    "asset_spec", ROOT / "scripts/asset_spec.py"
)
asset = importlib.util.module_from_spec(module)
module.loader.exec_module(asset)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / "sources/catalog.json").read_text())
        self.spec = asset.make_spec(self.catalog)

    def test_unknowns_are_explicit_and_not_ready(self):
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"])
        self.assertGreater(len(report["unresolved_fields"]), 0)
        self.assertFalse(report["dynamics_ready"])

    def test_invented_numeric_default_fails(self):
        self.spec["parts"]["a"]["mass"]["value"] = 0.001
        self.assertTrue(asset.audit(self.spec, self.catalog)["schema_errors"])

    def test_fake_reference_fails(self):
        field = self.spec["parts"]["a"]["mass"]
        field.update(
            value=0.001,
            status="derived",
            evidence=["nonexistent"],
            applicability="test",
        )
        self.assertTrue(asset.audit(self.spec, self.catalog)["schema_errors"])

    def test_unit_mismatch_fails(self):
        field = self.spec["parts"]["a"]["mass"]
        field.update(
            value=1,
            unit="g",
            status="derived",
            evidence=["xbox_visual"],
            applicability="synthetic negative test",
        )
        self.assertTrue(asset.audit(self.spec, self.catalog)["schema_errors"])

    def test_changed_sources_fail(self):
        changed = copy.deepcopy(self.catalog)
        changed["reference_values"]["front_force"]["value"] = 999
        self.assertTrue(asset.audit(self.spec, changed)["schema_errors"])

    def test_components_cannot_disappear(self):
        del self.spec["parts"]["dpad"]
        self.assertTrue(asset.audit(self.spec, self.catalog)["schema_errors"])

    def test_target_is_1708_without_share(self):
        self.assertEqual(self.spec["hardware_revision"]["value"], "1708")
        self.assertNotIn("share", self.spec["parts"])
        self.spec["parts"]["share"] = copy.deepcopy(self.spec["parts"]["a"])
        self.assertTrue(asset.audit(self.spec, self.catalog)["schema_errors"])

    def test_silent_target_swap_fails(self):
        self.spec["hardware_revision"]["value"] = "1914"
        self.assertTrue(asset.audit(self.spec, self.catalog)["schema_errors"])

    def test_reference_unit_conversion(self):
        refs = self.catalog["reference_values"]
        self.assertAlmostEqual(refs["stick_operating_torque"]["value"], 14 / 1000)
        self.assertAlmostEqual(refs["stick_click_travel"]["upper"], (0.4 + 0.5) / 1000)
        self.assertAlmostEqual(refs["front_travel"]["value"], 1.3 / 1000)
        for field in refs.values():
            self.assertIn(field["evidence"], self.catalog["sources"])
            self.assertTrue(field["locator"])


if __name__ == "__main__":
    unittest.main()
