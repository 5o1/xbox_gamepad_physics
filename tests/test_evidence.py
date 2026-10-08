import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "asset_spec", ROOT / "scripts/asset_spec.py"
)
asset = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(asset)


def load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load("sources/catalog.json")
        self.registry = load("assets/asset_index.json")
        self.spec = load("specs/xbox_v1.json")

    def audit(self, specification=None, *, catalog=None, registry=None):
        return asset.audit(
            self.spec if specification is None else specification,
            self.catalog if catalog is None else catalog,
            asset_registry=self.registry if registry is None else registry,
        )

    def test_checked_in_spec_is_valid_but_not_dynamics_ready(self):
        report = self.audit()
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertFalse(report["dynamics_ready"])
        self.assertGreater(len(report["unresolved_fields"]), 0)

    def test_unknown_physics_is_explicit(self):
        topology = self.spec["physical_topology"]
        self.assertEqual(topology["status"], "unknown")
        self.assertEqual(topology["bodies"], [])
        for name, part in self.spec["parts"].items():
            with self.subTest(part=name):
                model = part["motion_model"]
                self.assertEqual(model["status"], "unknown")
                self.assertEqual(model["joints"], [])

    def test_checked_in_spec_is_synchronizer_fixed_point(self):
        self.assertEqual(
            self.spec,
            asset.synchronize_spec(self.spec, self.catalog, self.registry),
        )

    def test_catalog_and_registry_hashes_are_current(self):
        self.assertEqual(
            self.spec["catalog_sha256"], asset._document_sha256(self.catalog)
        )
        self.assertEqual(
            self.spec["asset_registry_binding"]["sha256"],
            asset._document_sha256(self.registry),
        )

    def test_catalog_or_registry_drift_fails_closed(self):
        changed_catalog = copy.deepcopy(self.catalog)
        changed_catalog["checked_on"] = "tampered"
        self.assertFalse(self.audit(catalog=changed_catalog)["schema_valid"])

        changed_registry = copy.deepcopy(self.registry)
        changed_registry["target_hardware"]["model"] = "Xbox Series X|S"
        self.assertFalse(self.audit(registry=changed_registry)["schema_valid"])

    def test_target_model_cannot_be_silently_replaced(self):
        self.assertEqual(self.spec["target_model"]["value"], "Xbox One S")
        self.assertEqual(self.registry["target_hardware"]["model"], "Xbox One S")
        changed = copy.deepcopy(self.spec)
        changed["target_model"]["value"] = "Xbox Series X|S"
        self.assertFalse(self.audit(changed)["schema_valid"])

    def test_standard_interface_has_exactly_21_owned_channels(self):
        channels = self.spec["input_schema"]["channels"]
        self.assertEqual(len(channels), 21)
        self.assertEqual(
            [channel["tensor_index"] for channel in channels], list(range(21))
        )
        self.assertEqual(
            [channel["name"] for channel in channels],
            list(asset.CANONICAL_CHANNELS),
        )
        represented = [
            channel
            for control in asset.CONTROL_EFFECTS.values()
            for channel in control
        ]
        self.assertCountEqual(represented, asset.CANONICAL_CHANNELS)
        self.assertNotIn("share", self.spec["parts"])

    def test_visual_candidates_are_not_physics_approval(self):
        self.assertEqual(
            self.registry["approved_target_appearance_candidate_id"],
            self.registry["primary_appearance_candidate_id"],
        )
        self.assertIsNone(self.registry["approved_metric_geometry_variant_id"])
        self.assertIsNone(self.registry["physical_asset"]["collision_asset"])
        self.assertIsNone(self.registry["physical_asset"]["simulator_asset"])
        self.assertFalse(self.registry["physical_asset"]["contact_dynamics_validated"])
        legacy = self.registry["unapproved_collision_candidates"]
        self.assertFalse(legacy["shape_revision_match"])
        self.assertFalse(legacy["approved_for_simulation"])


if __name__ == "__main__":
    unittest.main()
