import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def resolve_from_assets(relative_path):
    return (ROOT / "assets" / relative_path).resolve()


class AssetRegistryTest(unittest.TestCase):
    def setUp(self):
        self.index = load("assets/asset_index.json")

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

    def test_registered_local_files_exist(self):
        for candidate in self.index["candidates"].values():
            for field in ("source", "front_render"):
                if field not in candidate:
                    continue
                with self.subTest(candidate=candidate["title"], field=field):
                    self.assertTrue(resolve_from_assets(candidate[field]).is_file())

        for variant_id, variant in self.index["derived_variants"].items():
            with self.subTest(variant=variant_id):
                if "inventory" in variant:
                    inventory = resolve_from_assets(variant["inventory"])
                    self.assertTrue(inventory.is_file())
                profile_binding = variant.get("viewer_profile")
                if profile_binding is not None:
                    self.assertEqual(
                        profile_binding,
                        {"route": "/generated/kinematics/xbox_one_s_estimated_v0.json"},
                    )

        for profile_id, profile in self.index.get(
            "partial_physics_profiles", {}
        ).items():
            with self.subTest(partial_profile=profile_id):
                self.assertFalse(profile["full_controller_ready"])
                self.assertFalse(profile["hardware_calibrated"])
                for path_field in ("source", "manifest"):
                    path = resolve_from_assets(profile[path_field])
                    self.assertTrue(path.is_file())

        for profile_id, profile in self.index.get("simulation_profiles", {}).items():
            with self.subTest(simulation_profile=profile_id):
                self.assertFalse(profile["hardware_calibrated"])
                self.assertEqual(
                    profile["status"],
                    "implemented_pending_user_review_and_hardware_calibration",
                )
                for path_field in ("source", "manifest"):
                    path = resolve_from_assets(profile[path_field])
                    self.assertTrue(path.is_file())

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
