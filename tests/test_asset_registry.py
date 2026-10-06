import json
import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class AssetRegistryTest(unittest.TestCase):
    def setUp(self):
        self.index = load("assets/asset_index.json")

    def test_registry_is_the_single_current_state_authority(self):
        self.assertEqual(self.index["schema_version"], 1)
        self.assertEqual(self.index["registry_role"], "canonical_status_authority")
        primary = self.index["primary_appearance_candidate_id"]
        self.assertIn(primary, self.index["candidates"])
        self.assertIsNone(self.index["approved_target_geometry_candidate_id"])

        evidence = load("sources/xbox_replacement_candidates.json")
        self.assertEqual(evidence["status_authority"], "../assets/asset_index.json")
        self.assertEqual(evidence["primary_appearance_candidate_id"], primary)
        self.assertEqual(
            evidence["accepted_geometry_candidate_id"],
            self.index["approved_target_geometry_candidate_id"],
        )
        records = {item["candidate_id"]: item for item in evidence["candidates"]}
        self.assertIn(primary, records)
        self.assertIn("has acknowledged", records[primary]["observed_geometry"])
        self.assertNotIn("pending user confirmation", records[primary]["observed_geometry"])

    def test_viewer_variant_cannot_be_mistaken_for_primary_candidate(self):
        active = self.index["interactive_viewer"]["active_variant_id"]
        variant = self.index["derived_variants"][active]
        self.assertIn(variant["source_candidate_id"], self.index["candidates"])
        self.assertNotEqual(
            variant["source_candidate_id"],
            self.index["primary_appearance_candidate_id"],
        )
        self.assertIs(variant["approved_for_contact_or_training"], False)
        self.assertIn("software regression only", self.index["interactive_viewer"]["verification_scope"])

    def test_geometry_gate_names_the_primary_candidate(self):
        acceptance = load("specs/interactive_acceptance.json")
        gate = next(g for g in acceptance["acceptance_gates"] if g["id"] == "geometry_identity")
        self.assertEqual(gate["candidate_id"], self.index["primary_appearance_candidate_id"])
        self.assertIs(gate["passed"], False)
        self.assertIn("appearance", gate["check"].lower())

    def test_referenced_local_registry_artifacts_exist(self):
        for candidate in self.index["candidates"].values():
            for field in ("source", "front_render"):
                target = (ROOT / "assets" / candidate[field]).resolve()
                self.assertTrue(target.is_file(), f"missing {field}: {target}")
        for variant in self.index["derived_variants"].values():
            target = (ROOT / "assets" / variant["inventory"]).resolve()
            self.assertTrue(target.is_file(), f"missing inventory: {target}")
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), variant["inventory_sha256"])
        revision = self.index["evidence"]["hardware_revision"]
        self.assertEqual(set(revision), {"document", "entry"})
        document = (ROOT / "assets" / revision["document"]).resolve()
        catalog = json.loads(document.read_text(encoding="utf-8"))
        current = catalog
        for token in revision["entry"].split("."):
            current = current[token]
        self.assertEqual(current["kind"], "user_statement")

    def test_legacy_collision_candidates_are_identity_bound(self):
        candidate_id = "xbox_series_1914_casperh2o_visual"
        candidate = self.index["candidates"][candidate_id]
        collision = self.index["unapproved_collision_candidates"]
        expected = {
            "source_candidate_id": candidate_id,
            "source_inventory_sha256": candidate["visual_manifest"]["sha256"],
            "target_revision": self.index["target_hardware"]["revision"],
            "shape_revision_match": False,
            "approved_for_simulation": False,
        }
        self.assertEqual(
            candidate["title"], "CasperH2O Microsoft Xbox One visual model"
        )
        self.assertIn("Microsoft Xbox One.blend", candidate["upstream_model_label"])
        self.assertIn("1914", candidate["display_identity"])
        for key, value in expected.items():
            self.assertEqual(collision[key], value)
        self.assertTrue(
            collision["gpu_directory"].endswith(
                "/LEGACY_1914_native_unit_button_collision_candidates_NOT_VALIDATED"
            )
        )
        for field in ("audit", "assembly_diagnostic"):
            path = (ROOT / "assets" / collision[field]).resolve()
            self.assertTrue(path.is_file(), f"missing {field}: {path}")
            self.assertIn(
                "legacy_casper_1914_native_unit_button_collision_candidates",
                path.parts,
            )
            report = json.loads(path.read_text(encoding="utf-8"))
            for key, value in expected.items():
                self.assertEqual(report[key], value)


if __name__ == "__main__":
    unittest.main()
