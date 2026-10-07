import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_estimated_v0 as builder


class EstimatedV0Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence, cls.profile, cls.audit = builder.build()

    def test_profile_is_explicitly_not_physics(self):
        self.assertEqual(self.profile["status"], "estimated_kinematic_preview_not_physical_asset")
        self.assertFalse(self.profile["acceptance"]["physical_acceptance"])
        self.assertFalse(self.profile["acceptance"]["dynamics_ready"])
        self.assertFalse(self.profile["acceptance"]["geometry_identity_verified"])

    def test_uniform_width_scale_keeps_other_dimension_residuals(self):
        fit = self.evidence["scale_fit"]
        self.assertAlmostEqual(fit["estimated_extents_m"][0], 0.153, places=12)
        self.assertNotEqual(fit["residuals_m"][1], 0)
        self.assertNotEqual(fit["residuals_m"][2], 0)
        self.assertEqual(fit["selection"], "width_exact_uniform_scale")

    def test_all_standard_channels_are_driven_once(self):
        driven = []
        for joint in self.profile["joints"]:
            driver = joint["driver"]
            if driver["kind"] == "linear_channel":
                driven.append(driver["channel"])
            elif driver["kind"] == "difference_channels":
                driven.extend([driver["negative_channel"], driver["positive_channel"]])
        self.assertEqual(sorted(driven), list(range(21)))
        pair = next(joint for joint in self.profile["joints"] if joint["id"] == "pair_press")
        self.assertEqual(pair["driver"]["kind"], "physical_event")

    def test_every_joint_parameter_is_bound_and_unknown_dynamics_are_null(self):
        parameters = self.evidence["parameters"]
        for joint in self.profile["joints"]:
            for reference in ("parameter_ref", "axis_parameter_ref", "pivot_parameter_ref"):
                self.assertIn(joint[reference], parameters)
                record = parameters[joint[reference]]
                self.assertTrue(record["evidence"])
                self.assertEqual(record["harness"]["path"], "scripts/build_estimated_v0.py")
        self.assertTrue(all(value["value"] is None for value in self.evidence["unknown_physical_parameters"].values()))

    def test_artist_pivots_are_nonzero_and_reconstruct_sampled_transforms(self):
        rotating = [joint for joint in self.profile["joints"] if joint["type"] == "revolute"]
        self.assertTrue(all(math.sqrt(sum(value * value for value in joint["pivot_source_m"])) > 0.005 for joint in rotating))
        validation = self.evidence["artist_pivot_validation"]
        self.assertTrue(validation["passed"])
        self.assertTrue(all(value <= validation["numerical_gate_native"] for value in validation["maximum_residuals_native"].values()))

    def test_visual_nodes_are_complete_and_unique(self):
        nodes = self.profile["nodes"]
        self.assertEqual(len(nodes), 16)
        self.assertEqual(len({node["source_node"] for node in nodes}), 16)
        self.assertEqual({node["control"] for node in nodes}, set(builder.PART_TO_CONTROL.values()))

    def test_stick_limit_is_reference_not_target_claim(self):
        record = self.evidence["parameters"]["stick_tilt_limit"]
        self.assertAlmostEqual(record["value"], math.radians(23))
        self.assertEqual(record["status"], "reference")
        self.assertIn("unconfirmed", record["applicability"])

    def test_stick_joint_space_circle_is_quantified_as_a_conservative_approximation(self):
        approximation = self.evidence["constraint_approximations"]["stick_joint_space_envelope"]
        limit = math.radians(23)
        diagonal = math.acos(math.cos(limit / math.sqrt(2)) ** 2)
        self.assertEqual(
            approximation["status"],
            "conservative_joint_space_approximation_not_physical_gate",
        )
        self.assertAlmostEqual(approximation["inclination_range_on_joint_space_boundary_rad"][0], diagonal)
        self.assertAlmostEqual(approximation["inclination_range_on_joint_space_boundary_rad"][1], limit)
        self.assertAlmostEqual(approximation["maximum_inclination_shortfall_rad"], limit - diagonal)
        self.assertGreater(approximation["maximum_inclination_shortfall_rad"], 0)
        sampled = []
        for index in range(7200):
            azimuth = 2 * math.pi * index / 7200
            horizontal = limit * math.cos(azimuth)
            vertical = limit * math.sin(azimuth)
            sampled.append(math.acos(math.cos(horizontal) * math.cos(vertical)))
        self.assertGreaterEqual(min(sampled), diagonal - 1e-12)
        self.assertLessEqual(max(sampled), limit + 1e-12)
        self.assertAlmostEqual(min(sampled), diagonal, places=12)
        self.assertAlmostEqual(max(sampled), limit, places=12)
        for constraint in self.profile["constraints"][:2]:
            self.assertEqual(constraint["coordinate_space"], "joint_coordinates")
            self.assertEqual(constraint["approximation_ref"], "stick_joint_space_envelope")

    def test_all_upstream_evidence_and_generated_outputs_are_hash_bound(self):
        bindings = self.evidence["source_bindings"]
        for path, expected in (
            (builder.DIMENSIONS, builder.EXPECTED_DIMENSIONS_SHA256),
            (builder.STICK_REFERENCE, builder.EXPECTED_STICK_REFERENCE_SHA256),
            (builder.CATALOG, builder.EXPECTED_CATALOG_SHA256),
        ):
            self.assertEqual(builder.sha256(path), expected)
        self.assertEqual(bindings["dimension_evidence_sha256"], builder.EXPECTED_DIMENSIONS_SHA256)
        self.assertEqual(bindings["stick_reference_sha256"], builder.EXPECTED_STICK_REFERENCE_SHA256)
        self.assertEqual(bindings["evidence_catalog_sha256"], builder.EXPECTED_CATALOG_SHA256)
        self.assertNotIn(str(builder.AUDIT_OUTPUT.relative_to(builder.ROOT)), self.audit["output_sha256"])
        self.assertEqual(
            self.audit["output_sha256"][str(builder.EVIDENCE_OUTPUT.relative_to(builder.ROOT))],
            builder.hashlib.sha256(builder.encoded(self.evidence)).hexdigest(),
        )
        self.assertEqual(
            self.audit["output_sha256"][str(builder.PROFILE_OUTPUT.relative_to(builder.ROOT))],
            builder.hashlib.sha256(builder.encoded(self.profile)).hexdigest(),
        )

    def test_every_parameter_evidence_id_resolves_in_pinned_catalog(self):
        available = set(self.evidence["evidence_index"]["available_ids"])
        self.assertEqual(self.evidence["evidence_index"]["catalog_sha256"], builder.EXPECTED_CATALOG_SHA256)
        for name, record in self.evidence["parameters"].items():
            self.assertTrue(record["evidence"], name)
            self.assertLessEqual(set(record["evidence"]), available, name)

    def test_catalog_citation_drift_is_rejected_before_generation(self):
        mutated = json.loads(builder.CATALOG.read_text(encoding="utf-8"))
        mutated["sources"]["alps_stick"]["url"] = "https://example.invalid/drift"
        original_path = builder.CATALOG
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "catalog.json"
            candidate.write_text(json.dumps(mutated), encoding="utf-8")
            builder.CATALOG = candidate
            try:
                with self.assertRaisesRegex(ValueError, "evidence catalog hash changed"):
                    builder.build()
            finally:
                builder.CATALOG = original_path

    def test_checked_in_generated_outputs_are_fresh(self):
        for path, value in zip(
            (builder.EVIDENCE_OUTPUT, builder.PROFILE_OUTPUT, builder.AUDIT_OUTPUT),
            (self.evidence, self.profile, self.audit),
        ):
            self.assertEqual(path.read_bytes(), builder.encoded(value), f"stale generated output: {path}")


if __name__ == "__main__":
    unittest.main()
