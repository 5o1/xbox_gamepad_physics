import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def resolve_from_assets(relative_path):
    return (ROOT / "src/xbox_gamepad_physics/resource_data" / relative_path).resolve()


class AssetRegistryTest(unittest.TestCase):
    def setUp(self):
        self.index = load("src/xbox_gamepad_physics/resource_data/asset_index.json")

    def test_registry_states_current_acceptance_boundary(self):
        self.assertEqual(self.index["registry_role"], "canonical_status_authority")
        self.assertEqual(self.index["target_hardware"]["model"], "Xbox One S")
        primary = self.index["primary_appearance_candidate_id"]
        self.assertIn(primary, self.index["candidates"])
        self.assertEqual(self.index["approved_target_appearance_candidate_id"], primary)
        self.assertTrue(
            self.index["candidates"][primary]["target_appearance_approval"]["approved"]
        )
        self.assertIsNone(self.index["approved_metric_geometry_variant_id"])
        physical = self.index["physical_asset"]
        self.assertIsNone(physical["collision_asset"])
        self.assertIsNone(physical["simulator_asset"])
        self.assertFalse(physical["contact_dynamics_validated"])

    def test_registered_local_files_exist_and_hashes_match(self):
        for candidate in self.index["candidates"].values():
            for field in ("source", "front_render"):
                with self.subTest(candidate=candidate["title"], field=field):
                    self.assertTrue(resolve_from_assets(candidate[field]).is_file())

        for variant_id, variant in self.index["derived_variants"].items():
            with self.subTest(variant=variant_id):
                inventory = resolve_from_assets(variant["inventory"])
                self.assertTrue(inventory.is_file())
                self.assertEqual(
                    hashlib.sha256(inventory.read_bytes()).hexdigest(),
                    variant["inventory_sha256"],
                )
                profile_binding = variant.get("viewer_profile")
                if profile_binding is not None:
                    profile = resolve_from_assets(profile_binding["path"])
                    self.assertTrue(profile.is_file())
                    self.assertEqual(
                        hashlib.sha256(profile.read_bytes()).hexdigest(),
                        profile_binding["sha256"],
                    )

    def test_legacy_1914_assets_cannot_become_xbox_one_s_physics(self):
        active_id = self.index["interactive_viewer"]["active_variant_id"]
        active = self.index["derived_variants"][active_id]
        self.assertEqual(
            active["source_candidate_id"],
            self.index["primary_appearance_candidate_id"],
        )
        self.assertTrue(active["target_appearance_approval"]["approved"])

        legacy = self.index["derived_variants"][
            "legacy_casper_1914_width_scaled_proxy"
        ]
        self.assertFalse(legacy["approved_for_contact_or_training"])
        self.assertFalse(legacy["collision_approved"])

        collision = self.index["unapproved_collision_candidates"]
        source = self.index["candidates"][collision["source_candidate_id"]]
        self.assertIn("1914", source["display_identity"])
        self.assertEqual(
            collision["target_model"], self.index["target_hardware"]["model"]
        )
        self.assertFalse(collision["shape_revision_match"])
        self.assertFalse(collision["approved_for_simulation"])


if __name__ == "__main__":
    unittest.main()
