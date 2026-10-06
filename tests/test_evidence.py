import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
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
        self.asset_registry = json.loads((ROOT / "assets/asset_index.json").read_text())
        self.spec = asset.make_spec(self.catalog)

    @staticmethod
    def evidence_field(value, unit):
        return {
            "value": value,
            "unit": unit,
            "status": "derived",
            "evidence": ["xbox_visual"],
            "harness": {
                "kind": "python_derivation",
                "path": "tests/test_evidence.py",
                "entrypoint": "EvidenceTests.evidence_field",
            },
            "applicability": "Only exercises the schema; not adopted as Xbox physical evidence.",
            "derivation": {
                "method": "Constructed directly by the schema test fixture.",
                "inputs": [{
                    "name": "fixture_value",
                    "value": value,
                    "unit": unit,
                    "evidence": ["xbox_visual"],
                }],
                "evidence": ["xbox_visual"],
            },
            "uncertainty": {
                "type": "bounded_error",
                "range": [0, 0],
                "unit": unit,
                "quantity": "Difference between the constructed fixture and itself",
                "confidence": {
                    "kind": "non_statistical",
                    "level": None,
                    "meaning": "Exact construction inside a schema test; not a physical confidence claim.",
                },
            },
        }

    @staticmethod
    def pose():
        return {"xyz": [0, 0, 0], "rpy": [0, 0, 0]}

    @staticmethod
    def schema_harness(entrypoint="EvidenceTests.set_topology"):
        return {
            "kind": "python_test",
            "path": "tests/test_evidence.py",
            "entrypoint": entrypoint,
        }

    @staticmethod
    def absent_field(name):
        return asset.intentionally_absent(
            name,
            evidence=["xbox_visual"],
            harness="synthetic schema fixture",
            reason="The synthetic fixture intentionally omits this property; no dummy simulator value is inserted.",
            applicability="Schema expressiveness test only; not an Xbox physical claim.",
        )

    @staticmethod
    def collider_common():
        return {
            "collision_filter": {
                "backend": "sapien_physx_v3",
                "word0_contact_type": 1,
                "word1_contact_affinity": 0xFFFFFFFF,
                "word2_ignore_bits": 0,
                "word3_id": 0,
                "semantics": "sapien_set_collision_groups_four_word_rule",
            },
            "contact_offset": 0.001,
            "rest_offset": 0.0,
            "offset_unit": "m",
        }

    def sphere_collider(self):
        return {
            "type": "sphere",
            "frame": "body",
            "pose": self.pose(),
            "pose_unit": "m,rad",
            **self.collider_common(),
            "radius": 0.005,
            "radius_unit": "m",
        }

    def visual_mesh(self, object_id="MainBody"):
        records = {
            record["name"]: record
            for record in json.loads(
                (ROOT / "results/legacy_casper_1914_width_scaled_1708_proxy/inventory.json").read_text()
            )["objects"]
        }
        record = records[object_id]
        return {
            "type": "mesh",
            "candidate_id": "legacy_casper_1914_width_scaled_1708_proxy",
            "artifact_id": "width_scaled_obj",
            "object_id": object_id,
            "frame": "body",
            "pose": self.pose(),
            "pose_unit": "m,rad",
            "file": record["file"],
            "sha256": record["sha256"],
            "meters_per_native_unit": [1, 1, 1],
            "meters_per_native_unit_unit": "m/native_unit",
            "materials": {"mode": "none", "files": []},
        }

    def approved_visual_registry(self):
        registry = copy.deepcopy(self.asset_registry)
        candidate_id = "synthetic_1708_target_visual_fixture"
        registry["approved_target_geometry_candidate_id"] = candidate_id
        manifest = copy.deepcopy(
            registry["derived_variants"][
                "legacy_casper_1914_width_scaled_1708_proxy"
            ]["visual_manifest"]
        )
        scale_field = self.evidence_field([1, 1, 1], "m/native_unit")
        scale_field["derivation"]["inputs"][0]["name"] = (
            "derived_meters_per_native_unit"
        )
        manifest["artifacts"]["width_scaled_obj"]["metric_scale"] = scale_field
        registry["candidates"][candidate_id] = {
            "title": "Synthetic schema-only 1708 visual fixture",
            "status": "synthetic_schema_fixture_not_a_project_asset",
            "controller_revision_verified": True,
            "dimensions_verified": True,
            "mechanically_verified": False,
            "approved_for_contact_or_training": False,
            "visual_manifest": manifest,
            "target_visual_geometry_approval": {
                "approved": True,
                "target_revision": "1708",
                "shape_identity_verified": True,
                "evidence": [{
                "path": "sources/catalog.json",
                "sha256": hashlib.sha256((ROOT / "sources/catalog.json").read_bytes()).hexdigest(),
                }],
                "reason": "Synthetic in-memory registry mutation used only by schema tests.",
            },
        }
        return registry

    def approved_visual_mesh(self, object_id="MainBody"):
        visual = self.visual_mesh(object_id)
        visual["candidate_id"] = "synthetic_1708_target_visual_fixture"
        return visual

    def body(self, body_id, owner="shared", collider=None, visual=None):
        body = {
            "id": body_id,
            "body_owner": self.evidence_field(owner, None),
            "body_role": self.evidence_field("physical", None),
            "visual_geometry": (
                self.absent_field("visual_geometry")
                if visual is None
                else self.evidence_field(visual, asset.UNITS["visual_geometry"])
            ),
            "mass": self.evidence_field(0.01, asset.UNITS["mass"]),
            "center_of_mass": self.evidence_field(
                {"xyz": [0, 0, 0], "expressed_in": "body_frame"},
                asset.UNITS["center_of_mass"],
            ),
            "inertia": self.evidence_field(
                {
                    "matrix": [[1e-6, 0, 0], [0, 1e-6, 0], [0, 0, 1e-6]],
                    "about": "center_of_mass",
                    "expressed_in": "body_frame",
                },
                asset.UNITS["inertia"],
            ),
            "collision_geometry": self.absent_field("collision_geometry"),
            "contact_friction": self.absent_field("contact_friction"),
            "contact_restitution": self.absent_field("contact_restitution"),
        }
        if collider is not None:
            body["collision_geometry"] = self.evidence_field(
                collider, asset.UNITS["collision_geometry"]
            )
            body["contact_friction"] = self.evidence_field(
                {
                    "static_friction": 0.5,
                    "dynamic_friction": 0.4,
                    "combine_mode": "average",
                },
                asset.UNITS["contact_friction"],
            )
            body["contact_restitution"] = self.evidence_field(
                {"coefficient": 0.0, "combine_mode": "average"},
                asset.UNITS["contact_restitution"],
            )
        return body

    def virtual_body(self, body_id, owner="shared"):
        body = self.body(body_id, owner)
        body["body_role"] = self.evidence_field("virtual_frame", None)
        for key in asset.BODY_PROPERTY_FIELDS:
            body[key] = self.absent_field(key)
        return body

    def set_topology(self, bodies, status="modeled", constraints=None):
        root_body = bodies[0]["id"] if bodies else None
        self.spec["physical_topology"].update(
            status=status,
            bodies=bodies,
            configuration_constraints=constraints or [],
            harness=self.schema_harness("EvidenceTests.set_topology"),
            root_attachment={
                "status": "modeled",
                "mode": "fixed_to_fixture",
                "root_body": root_body,
                "reference_frame": "fixture",
                "pose": self.pose(),
                "pose_unit": "m,rad",
                "pose_evidence": self.evidence_field(self.pose(), "m,rad"),
                "evidence": ["xbox_visual"],
                "harness": self.schema_harness("EvidenceTests.set_topology"),
                "reason": None,
                "applicability": "Synthetic topology only; not an Xbox mounting claim.",
            },
            self_collision_policy={
                "status": "modeled",
                "default": "disabled",
                "pair_overrides": [],
                "evidence": ["xbox_visual"],
                "harness": self.schema_harness("EvidenceTests.set_topology"),
                "reason": None,
                "applicability": "Synthetic topology only; not an Xbox contact claim.",
            },
            evidence=["xbox_visual"],
            reason=None,
            applicability="Synthetic body graph used only to exercise schema expressiveness.",
        )

    def joint(self, joint_id, joint_type, parent, child, effects):
        units = asset.JOINT_UNITS[joint_type]
        if joint_type == "prismatic":
            lower, upper = 0.0, 0.002
        else:
            lower, upper = -0.2, 0.2
        coordinates = effects[0][1] if effects else []
        neutral_candidates = [
            point[0]
            for point in coordinates
            if all(
                any(other[0] == point[0] and other[1] == 0 for other in curve)
                for _channel, curve in effects
            )
        ]
        equilibrium = 0.0 if 0.0 in neutral_candidates else (
            neutral_candidates[0] if neutral_candidates else 0.0
        )
        restoring_curve = (
            [[lower, 0.1], [equilibrium, 0.0], [upper, -0.1]]
            if lower < equilibrium < upper
            else [[lower, 0.0], [upper, -0.1]]
        )
        limits = (
            {"unbounded": True}
            if joint_type == "continuous"
            else {"lower": lower, "upper": upper}
        )
        analog = bool(effects) and all(
            channel in asset.ANALOG_CHANNELS for channel, _curve in effects
        )
        if analog:
            input_mapping = {
                "model": "analog_monotone",
                "effects": [
                    {
                        "channel": channel,
                        "curve": curve,
                        "direction": (
                            "strictly_increasing"
                            if all(curve[index][1] < curve[index + 1][1] for index in range(len(curve) - 1))
                            else "strictly_decreasing"
                            if all(curve[index][1] > curve[index + 1][1] for index in range(len(curve) - 1))
                            else "nondecreasing"
                            if all(curve[index][1] <= curve[index + 1][1] for index in range(len(curve) - 1))
                            else "nonincreasing"
                        ),
                    }
                    for channel, curve in effects
                ],
                "interpolation": "piecewise_linear",
                "outside_domain": "reject",
                "inverse_policy": "unique_monotone_effect_tuple",
                "neutral_coordinate": equilibrium,
            }
        else:
            transitions = []
            representatives = [{
                "output_state": [0] * max(1, len(effects)),
                "coordinate": equilibrium,
            }]
            for effect_index, (channel, curve) in enumerate(effects):
                side = "negative" if curve[0][1] > curve[-1][1] else "positive"
                endpoint = lower if side == "negative" else upper
                press = equilibrium + 0.5 * (endpoint - equilibrium)
                release = equilibrium + 0.25 * (endpoint - equilibrium)
                transitions.append({
                    "channel": channel,
                    "pressed_side": side,
                    "press_threshold": press,
                    "release_threshold": release,
                })
                state = [0] * len(effects)
                state[effect_index] = 1
                representatives.append({"output_state": state, "coordinate": endpoint})
            if effects:
                output_kind = "standard_channels"
                physical_event = None
            else:
                output_kind = "physical_event"
                physical_event = {
                    "name": "pair_bind_connect",
                    "pressed_side": "positive",
                    "press_threshold": equilibrium + 0.5 * (upper - equilibrium),
                    "release_threshold": equilibrium + 0.25 * (upper - equilibrium),
                }
                representatives.append({"output_state": [1], "coordinate": upper})
            input_mapping = {
                "model": "digital_hysteresis",
                "output_kind": output_kind,
                "effects": transitions,
                "physical_event": physical_event,
                "coordinate_domain": [lower, upper],
                "outside_domain": "reject",
                "initial_state": [0] * max(1, len(effects)),
                "state_semantics": "schmitt_trigger_retains_state_between_thresholds",
                "inverse_policy": "representative_coordinates_not_unique_inverse",
                "inverse_representatives": representatives,
                "neutral_coordinate": equilibrium,
            }
        return {
            "id": joint_id,
            "parent_body": self.evidence_field(parent, None),
            "child_body": self.evidence_field(child, None),
            "joint_type": self.evidence_field(joint_type, None),
            "actuation_mode": self.evidence_field("passive", None),
            "joint_origin": self.evidence_field(
                {**self.pose(), "relative_to": "parent_body"}, units["joint_origin"]
            ),
            "joint_axis": self.evidence_field(
                {"xyz": [0, 0, 1], "expressed_in": "joint_frame"},
                units["joint_axis"],
            ),
            "joint_limits": self.evidence_field(
                limits, units["joint_limits"]
            ),
            "actuator_effort_limit": asset.intentionally_absent(
                "actuator_effort_limit",
                unit=units["actuator_effort_limit"],
                evidence=["xbox_visual"],
                harness="synthetic schema fixture",
                reason="A passive mechanism has no actuator effort limit; simulator clamps are separate.",
                applicability="Synthetic passive-joint fixture only.",
            ),
            "actuator_velocity_limit": asset.intentionally_absent(
                "actuator_velocity_limit",
                unit=units["actuator_velocity_limit"],
                evidence=["xbox_visual"],
                harness="synthetic schema fixture",
                reason="A passive mechanism has no actuator velocity limit; simulator clamps are separate.",
                applicability="Synthetic passive-joint fixture only.",
            ),
            "restoring_curve": self.evidence_field(
                {
                    "model": "single_valued_no_hysteresis",
                    "equilibrium_coordinate": equilibrium,
                    "coordinate_unit": "m" if joint_type == "prismatic" else "rad",
                    "positive_coordinate": "along_joint_axis" if joint_type == "prismatic" else "right_hand_about_joint_axis",
                    "effort_unit": "N" if joint_type == "prismatic" else "N*m",
                    "effort_quantity": "internal_generalized_effort_on_child",
                    "positive_effort": "along_positive_joint_coordinate",
                    "branches": {"single": restoring_curve},
                    "branch_selection": "single_valued",
                    "interpolation": "piecewise_linear",
                    "outside_domain": "reject",
                    "limitation": "Synthetic stable spring with no hysteresis; schema test only.",
                },
                units["restoring_curve"],
            ),
            "damping": self.evidence_field(0.1, units["damping"]),
            "joint_friction": self.evidence_field(0.01, units["joint_friction"]),
            "input_mapping": self.evidence_field(
                input_mapping,
                (
                    units["input_mapping"].replace("->1", "->physical_event")
                    if not effects
                    else units["input_mapping"]
                ),
            ),
        }

    def set_motion_model(self, component, joints, status="modeled"):
        model = self.spec["parts"][component]["motion_model"]
        model.update(
            status=status,
            joints=joints,
            evidence=["xbox_visual"],
            harness=self.schema_harness("EvidenceTests.set_motion_model"),
            reason=None,
            applicability="Synthetic topology used only to exercise schema expressiveness.",
        )
        if len(joints) > 1:
            model["configuration_domain"] = {
                "status": "unmodeled",
                "constraint_ids": [],
                "combination": None,
                "independent_joint_ids": [],
                "neutral_configuration": None,
                "neutral_configuration_evidence": asset.unknown(
                    "neutral_configuration", unit="per_joint_coordinate_units"
                ),
                "approximation": None,
                "evidence": ["xbox_visual"],
                "harness": self.schema_harness("EvidenceTests.set_motion_model"),
                "reason": "The synthetic multi-joint fixture explicitly leaves coupling unmodeled.",
                "applicability": "Schema test only; an exporter must reject rather than assume a rectangle.",
            }
        return model

    @staticmethod
    def constrained_domain(constraint_id, neutral_configuration, independent_joint_ids=None):
        return {
            "status": "constrained",
            "constraint_ids": [constraint_id],
            "combination": "intersection",
            "independent_joint_ids": independent_joint_ids or [],
            "neutral_configuration": neutral_configuration,
            "neutral_configuration_evidence": EvidenceTests.evidence_field(
                neutral_configuration, "per_joint_coordinate_units"
            ),
            "approximation": None,
            "evidence": ["xbox_visual"],
            "harness": EvidenceTests.schema_harness("EvidenceTests.constrained_domain"),
            "reason": None,
            "applicability": "Schema expressiveness test only; not an Xbox physical claim.",
        }

    @staticmethod
    def polar_constraint(constraint_id="left_stick_envelope"):
        return {
            "id": constraint_id,
            "type": "tabulated_polar_envelope",
            "joint_ids": ["left_tilt_x", "left_tilt_y"],
            "frame": "joint_coordinate_space",
            "coordinate_units": ["rad", "rad"],
            "center": [0.0, 0.0],
            "azimuth_unit": "rad",
            "radius_unit": "rad",
            "samples": [
                [0.0, 0.2],
                [math.pi / 4, 0.15],
                [math.pi / 2, 0.2],
                [3 * math.pi / 4, 0.15],
                [math.pi, 0.2],
                [5 * math.pi / 4, 0.15],
                [3 * math.pi / 2, 0.2],
                [7 * math.pi / 4, 0.15],
            ],
            "interpolation": "periodic_linear",
            "numeric_payload_evidence": EvidenceTests.evidence_field(
                {
                    "center": [0.0, 0.0],
                    "samples": [
                        [0.0, 0.2],
                        [math.pi / 4, 0.15],
                        [math.pi / 2, 0.2],
                        [3 * math.pi / 4, 0.15],
                        [math.pi, 0.2],
                        [5 * math.pi / 4, 0.15],
                        [3 * math.pi / 2, 0.2],
                        [7 * math.pi / 4, 0.15],
                    ],
                },
                "typed_by_constraint_schema",
            ),
            "evidence": ["xbox_visual"],
            "harness": EvidenceTests.schema_harness("EvidenceTests.polar_constraint"),
            "applicability": "Synthetic non-rectangular stick envelope; not an Xbox claim.",
        }

    def test_unknowns_are_empty_explicit_and_not_ready(self):
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertIn("physical_topology", report["unresolved_fields"])
        self.assertEqual(self.spec["physical_topology"]["bodies"], [])
        for component in asset.CONTROLS:
            model = self.spec["parts"][component]["motion_model"]
            self.assertEqual(model["status"], "unknown")
            self.assertEqual(model["joints"], [])
            self.assertIn(f"{component}.motion_model", report["unresolved_fields"])
        self.assertFalse(report["dynamics_ready"])
        self.assertIn(
            "physics_cooking_parameters_unresolved",
            {blocker["id"] for blocker in report["readiness_blockers"]},
        )

    def test_checked_in_spec_is_synchronizer_fixed_point(self):
        checked_in = json.loads((ROOT / "specs/xbox_v1.json").read_text())
        self.assertEqual(checked_in, asset.synchronize_spec(checked_in, self.catalog))

    def test_sync_preserves_future_measured_topology_and_motion_data(self):
        current = asset.make_spec(self.catalog)
        current["physical_topology"]["status"] = "future_measurement_marker"
        current["parts"]["left_stick"]["motion_model"]["joints"] = [
            {"future": "measured_joint"}
        ]
        synchronized = asset.synchronize_spec(current, self.catalog)
        self.assertEqual(synchronized["physical_topology"], current["physical_topology"])
        self.assertEqual(synchronized["parts"], current["parts"])

    def test_sync_preserves_edits_made_while_fields_remain_unknown(self):
        current = asset.make_spec(self.catalog)
        current["physical_topology"]["reason"] = "Measurement plan recorded before any body is entered."
        current["physical_topology"]["root_attachment"]["reason"] = "Fixture decision is pending review."
        current["parts"]["left_stick"]["motion_model"]["reason"] = "Gimbal inspection is scheduled."
        current["parts"]["left_stick"]["motion_model"]["configuration_domain"][
            "reason"
        ] = "Envelope measurement is scheduled."
        synchronized = asset.synchronize_spec(current, self.catalog)
        self.assertEqual(synchronized["physical_topology"], current["physical_topology"])
        self.assertEqual(synchronized["parts"], current["parts"])

    def test_sync_publish_candidate_is_audited_before_any_overwrite(self):
        current = asset.make_spec(self.catalog)
        current["physical_topology"]["stale_removed_field"] = True
        synchronized, report = asset.validated_synchronize_spec(current, self.catalog)
        self.assertIn("stale_removed_field", synchronized["physical_topology"])
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "physical_topology: fields changed" in error
            for error in report["schema_errors"]
        ))

    def test_sync_spec_check_is_read_only(self):
        path = ROOT / "specs/xbox_v1.json"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/asset_spec.py"), "sync-spec"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_audit_does_not_overwrite_reviewed_result_by_default(self):
        result = ROOT / "results/spec_audit.json"
        existed = result.exists()
        before = (result.read_bytes(), result.stat().st_mtime_ns) if existed else None
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/asset_spec.py"), "audit"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        if existed:
            self.assertEqual((result.read_bytes(), result.stat().st_mtime_ns), before)
        else:
            self.assertFalse(result.exists())

    def test_published_audit_is_bound_to_current_spec_and_catalog(self):
        spec = json.loads((ROOT / "specs/xbox_v1.json").read_text())
        published = json.loads((ROOT / "results/spec_audit.json").read_text())
        expected = asset.audit(spec, self.catalog)
        self.assertEqual(published, expected)
        self.assertEqual(published["report_schema_version"], asset.REPORT_SCHEMA_VERSION)
        self.assertEqual(published["spec_sha256"], asset._document_sha256(spec))
        self.assertEqual(published["catalog_sha256"], asset._catalog_sha256(self.catalog))
        self.assertEqual(
            published["asset_registry_sha256"],
            asset._document_sha256(self.asset_registry),
        )

    def test_schema1_viewer_is_hash_bound_and_blocked_from_physical_acceptance(self):
        gate = self.asset_registry["physical_asset"]["viewer_adapter"]
        acceptance_path = ROOT / gate["interactive_acceptance"]
        raw = acceptance_path.read_bytes()
        acceptance = json.loads(raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), gate["interactive_acceptance_sha256"])
        self.assertEqual(gate["status"], "blocked_unimplemented")
        self.assertIsNone(gate["implementation"])
        self.assertFalse(gate["physical_acceptance_allowed"])
        self.assertEqual(acceptance["canonical_adapter"]["status"], "blocked_unimplemented")
        adapter_gates = [
            item for item in acceptance["acceptance_gates"]
            if item["id"] == "canonical_v2_to_viewer_adapter"
        ]
        self.assertEqual(len(adapter_gates), 1)
        self.assertFalse(adapter_gates[0]["passed"])

        changed_registry = copy.deepcopy(self.asset_registry)
        changed_registry["physical_asset"]["viewer_adapter"][
            "interactive_acceptance_sha256"
        ] = "b" * 64
        report = asset.audit(self.spec, self.catalog, asset_registry=changed_registry)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("acceptance SHA256 mismatch" in error for error in report["schema_errors"]))

    def test_schema_version_is_exact(self):
        for bad in (1, 999, 2.0, "2", True, None):
            with self.subTest(bad=bad):
                changed = copy.deepcopy(self.spec)
                changed["schema_version"] = bad
                self.assertFalse(asset.audit(changed, self.catalog)["schema_valid"])

    def test_top_level_and_field_keys_are_strict(self):
        for mutate in (
            lambda spec: spec.update(approved=True),
            lambda spec: spec.update(status="ready_for_RL"),
            lambda spec: spec.update(topology_policy="trust the mesh"),
        ):
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(self.spec)
                mutate(changed)
                self.assertFalse(asset.audit(changed, self.catalog)["schema_valid"])
        changed = copy.deepcopy(self.spec)
        changed["hardware_revision"]["approved"] = True
        self.assertFalse(asset.audit(changed, self.catalog)["schema_valid"])

    def test_known_field_statuses_bind_provenance_uncertainty_and_existing_harnesses(self):
        common = {
            "value": 0.01,
            "unit": "kg",
            "evidence": ["xbox_visual"],
            "applicability": "Synthetic provenance fixture only; not an Xbox mass claim.",
        }
        uncertainty = {
            "type": "bounded_interval",
            "range": [0.009, 0.011],
            "unit": "kg",
            "quantity": "body mass",
            "confidence": {
                "kind": "engineering_bound",
                "level": None,
                "meaning": "The interval is a schema-test engineering bound, not a probability.",
            },
        }
        derivation = {
            "method": "Synthetic arithmetic identity used only to exercise provenance validation.",
            "inputs": [{
                "name": "fixture_mass_input",
                "value": 0.01,
                "unit": "kg",
                "evidence": ["xbox_visual"],
            }],
            "evidence": ["xbox_visual"],
        }
        derived = {
            **common,
            "status": "derived",
            "harness": {
                "kind": "python_derivation",
                "path": "scripts/asset_spec.py",
                "entrypoint": "_audit_field",
            },
            "derivation": derivation,
            "uncertainty": uncertainty,
        }
        estimated = copy.deepcopy(derived)
        estimated["status"] = "estimated"
        measured = {
            **common,
            "status": "measured",
            "harness": {
                "kind": "measurement_protocol",
                "path": "tests/test_evidence.py",
                "entrypoint": "EvidenceTests.test_known_field_statuses_bind_provenance_uncertainty_and_existing_harnesses",
            },
            "measurement": {
                "protocol_path": "tests/test_evidence.py",
                "instrument": {
                    "manufacturer": "Synthetic",
                    "model": "SchemaFixture",
                    "identifier": "fixture-only",
                    "resolution": 0.001,
                    "resolution_unit": "kg",
                },
                "sample_count": 3,
                "method": "Three synthetic observations; no target-hardware claim.",
            },
            "uncertainty": uncertainty,
        }
        reference = {
            **common,
            "status": "reference",
            "harness": {
                "kind": "reference_review",
                "path": "sources/catalog.json",
                "entrypoint": "sources.xbox_visual",
            },
            "reference": {
                "source_id": "xbox_visual",
                "adoption_rule": "Adopted only in this schema fixture; target applicability is explicitly denied above.",
            },
        }
        for field in (derived, estimated, measured, reference):
            with self.subTest(status=field["status"]):
                self.spec = asset.make_spec(self.catalog)
                body = self.body("fixture")
                body["mass"] = copy.deepcopy(field)
                self.set_topology([body])
                report = asset.audit(self.spec, self.catalog)
                self.assertTrue(report["schema_valid"], report["schema_errors"])

        invalid = []
        missing_derivation = copy.deepcopy(estimated)
        del missing_derivation["derivation"]
        invalid.append(missing_derivation)
        bad_uncertainty = copy.deepcopy(derived)
        bad_uncertainty["uncertainty"]["range"] = [0.02, 0.03]
        invalid.append(bad_uncertainty)
        missing_harness = copy.deepcopy(derived)
        missing_harness["harness"]["path"] = "scripts/does_not_exist.py"
        invalid.append(missing_harness)
        bad_measurement = copy.deepcopy(measured)
        bad_measurement["measurement"]["instrument"]["resolution"] = 0
        invalid.append(bad_measurement)
        bad_reference = copy.deepcopy(reference)
        bad_reference["reference"]["source_id"] = "not_a_catalog_source"
        invalid.append(bad_reference)
        for field in invalid:
            with self.subTest(invalid_status=field.get("status"), field=field):
                self.spec = asset.make_spec(self.catalog)
                body = self.body("fixture")
                body["mass"] = field
                self.set_topology([body])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_all_known_model_harnesses_are_existing_structured_entrypoints(self):
        constraint = {
            "id": "a_travel_domain",
            "type": "linear_inequality_set",
            "joint_ids": ["a_press"],
            "frame": "joint_coordinate_space",
            "coordinate_units": ["m"],
            "bound_unit": "m",
            "inequalities": [
                {"coefficients": [1], "operator": "<=", "bound": 0.002},
                {"coefficients": [1], "operator": ">=", "bound": 0.0},
            ],
            "numeric_payload_evidence": self.evidence_field(
                {"inequalities": [
                    {"coefficients": [1], "operator": "<=", "bound": 0.002},
                    {"coefficients": [1], "operator": ">=", "bound": 0.0},
                ]},
                "typed_by_constraint_schema",
            ),
            "evidence": ["xbox_visual"],
            "harness": self.schema_harness(
                "EvidenceTests.test_all_known_model_harnesses_are_existing_structured_entrypoints"
            ),
            "applicability": "Synthetic constraint used only for harness validation.",
        }
        self.set_topology([
            self.body("shell_body", "shell"), self.body("a_cap", "a")
        ], constraints=[constraint])
        self.set_motion_model("a", [self.joint(
            "a_press", "prismatic", "shell_body", "a_cap",
            [("a", [[0, 0], [0.002, 1]])],
        )])
        self.spec["parts"]["a"]["motion_model"]["configuration_domain"] = (
            self.constrained_domain(
                "a_travel_domain", {"a_press": 0.0}
            )
        )
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

        paths = (
            ("physical_topology", "harness"),
            ("physical_topology", "root_attachment", "harness"),
            ("physical_topology", "self_collision_policy", "harness"),
            ("physical_topology", "configuration_constraints", 0, "harness"),
            ("parts", "a", "motion_model", "harness"),
            ("parts", "a", "motion_model", "configuration_domain", "harness"),
        )
        for path in paths:
            with self.subTest(path=path):
                broken = copy.deepcopy(self.spec)
                cursor = broken
                for segment in path:
                    cursor = cursor[segment]
                cursor["entrypoint"] = "DoesNotExist"
                report = asset.audit(broken, self.catalog)
                self.assertFalse(report["schema_valid"])
                self.assertTrue(any(
                    "entrypoint does not exist" in error
                    for error in report["schema_errors"]
                ))

    def test_raw_root_pose_cannot_change_without_evidence_and_uncertainty_binding(self):
        self.set_topology([self.body("shell_body", "shell")])
        self.spec["physical_topology"]["root_attachment"]["pose"]["xyz"][0] = 0.1
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "pose_evidence: bound value disagrees" in error
            for error in report["schema_errors"]
        ))

    def test_non_numeric_non_finite_and_impossible_body_values_fail(self):
        cases = (
            ("mass", "not-a-mass"),
            ("mass", math.nan),
            ("mass", math.inf),
            ("mass", 0),
            ("contact_friction", -50),
            ("contact_restitution", 1.1),
            ("center_of_mass", [0, 0]),
            ("inertia", [[1, 2, 0], [0, 1, 0], [0, 0, 1]]),
        )
        for key, bad in cases:
            with self.subTest(key=key, bad=bad):
                self.spec = asset.make_spec(self.catalog)
                body = self.body("fixture")
                body[key]["value"] = bad
                self.set_topology([body])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_inertia_principal_moments_obey_rigid_body_triangle_inequality(self):
        body = self.body("fixture")
        body["inertia"]["value"] = {
            "matrix": [[10, 0, 0], [0, 1, 0], [0, 0, 1]],
            "about": "center_of_mass",
            "expressed_in": "body_frame",
        }
        self.set_topology([body])
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_contact_material_requires_explicit_physx_coefficients_and_modes(self):
        cases = (
            ("contact_friction", 0.5),
            (
                "contact_friction",
                {
                    "static_friction": 0.4,
                    "dynamic_friction": 0.5,
                    "combine_mode": "average",
                },
            ),
            (
                "contact_friction",
                {
                    "static_friction": 0.5,
                    "dynamic_friction": 0.4,
                    "combine_mode": "physx_default",
                },
            ),
            ("contact_restitution", 0.0),
            (
                "contact_restitution",
                {"coefficient": 0.0, "combine_mode": "bananas"},
            ),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.spec = asset.make_spec(self.catalog)
                body = self.body("fixture", collider=self.sphere_collider())
                body[key]["value"] = value
                self.set_topology([body])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_body_properties_are_not_stored_on_logical_controls(self):
        self.assertEqual(set(self.spec["parts"]["left_stick"]), {"motion_model"})
        self.spec["parts"]["left_stick"]["mass"] = self.evidence_field(0.1, "kg")
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_body_can_bind_multiple_visual_meshes_materials_and_source_identity(self):
        registry = self.approved_visual_registry()
        self.spec = asset.make_spec(self.catalog, asset_registry=registry)
        first = self.approved_visual_mesh("MainBody")
        second = self.approved_visual_mesh("A")
        body = self.body("shell_body", "shell", visual=[first, second])
        self.set_topology([body])
        report = asset.audit(self.spec, self.catalog, asset_registry=registry)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_visual_binding_path_frame_scale_hash_and_materials_are_strict(self):
        registry = self.approved_visual_registry()
        valid = self.approved_visual_mesh()
        changes = (
            {**valid, "candidate_id": "Not Stable"},
            {**valid, "frame": "part"},
            {**valid, "file": "../visual.glb"},
            {**valid, "sha256": "bad"},
            {**valid, "meters_per_native_unit": [1, 0, 1]},
            {**valid, "meters_per_native_unit_unit": "1"},
            {**valid, "materials": {"mode": "external", "files": []}},
        )
        for bad in changes:
            with self.subTest(bad=bad):
                self.spec = asset.make_spec(self.catalog, asset_registry=registry)
                body = self.body("shell_body", "shell", visual=bad)
                self.set_topology([body])
                self.assertFalse(asset.audit(
                    self.spec, self.catalog, asset_registry=registry
                )["schema_valid"])

        external = self.approved_visual_mesh()
        external["materials"] = {
            "mode": "external",
            "files": [{"file": "textures/albedo.png", "sha256": "a" * 64}],
        }
        self.spec = asset.make_spec(self.catalog, asset_registry=registry)
        self.set_topology([self.body("shell_body", "shell", visual=external)])
        report = asset.audit(self.spec, self.catalog, asset_registry=registry)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("external files are rejected" in error for error in report["schema_errors"]))

    def test_visual_candidate_must_resolve_in_bound_asset_registry(self):
        visual = self.visual_mesh()
        visual["candidate_id"] = "synthetic_overlay"
        body = self.body("shell_body", "shell", visual=visual)
        self.set_topology([body])
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(
            any("not present in the bound asset registry" in error for error in report["schema_errors"])
        )

    def test_sha_bound_registry_manifest_visual_is_accepted(self):
        registry = self.approved_visual_registry()
        self.spec = asset.make_spec(self.catalog, asset_registry=registry)
        body = self.body("shell_body", "shell", visual=self.approved_visual_mesh())
        self.set_topology([body])
        report = asset.audit(self.spec, self.catalog, asset_registry=registry)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_visual_identity_file_and_hash_must_match_manifest_object(self):
        registry = self.approved_visual_registry()
        valid = self.approved_visual_mesh()
        changes = (
            {**valid, "artifact_id": "not_registered"},
            {**valid, "object_id": "not_registered"},
            {**valid, "file": "different.obj"},
            {**valid, "sha256": "b" * 64},
        )
        for visual in changes:
            with self.subTest(change=visual):
                self.spec = asset.make_spec(self.catalog, asset_registry=registry)
                self.set_topology([self.body("shell_body", "shell", visual=visual)])
                self.assertFalse(asset.audit(
                    self.spec, self.catalog, asset_registry=registry
                )["schema_valid"])

    def test_rejected_1914_proxy_cannot_bind_to_target_physical_body(self):
        body = self.body("shell_body", "shell", visual=self.visual_mesh())
        self.set_topology([body])
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "is not approved for target visual geometry" in error
            for error in report["schema_errors"]
        ))

    def test_target_visual_scale_cannot_change_without_bound_derivation(self):
        registry = self.approved_visual_registry()
        scale_field = registry["candidates"][
            "synthetic_1708_target_visual_fixture"
        ]["visual_manifest"]["artifacts"]["width_scaled_obj"]["metric_scale"]
        scale_field["value"] = [2, 2, 2]
        self.spec = asset.make_spec(self.catalog, asset_registry=registry)
        visual = self.approved_visual_mesh()
        visual["meters_per_native_unit"] = [2, 2, 2]
        self.set_topology([self.body("shell_body", "shell", visual=visual)])
        report = asset.audit(self.spec, self.catalog, asset_registry=registry)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "metric-scale derivation" in error for error in report["schema_errors"]
        ))

    def test_primary_candidate_inventory_does_not_expose_unverified_artifact_binding(self):
        self.assertEqual(
            self.asset_registry["candidates"]["xbox_one_s_batonyrobson_a62cf747"]
            ["visual_manifest"]["artifacts"],
            {},
        )
        visual = self.visual_mesh()
        visual.update(
            candidate_id="xbox_one_s_batonyrobson_a62cf747",
            artifact_id="glb_2k",
            object_id="Controller Body_XBox Gamepad by Batony Robson_0",
            file="xbox/xbox_one_s_controllergamepad_animated.glb",
            sha256="5c5671c83a9cf15db4b8399e7010aa7d5cde915687ceb348b583eb00b0ed24e2",
        )
        body = self.body("shell_body", "shell", visual=visual)
        self.set_topology([body])
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("is not approved for target visual geometry" in error for error in report["schema_errors"]))

    def test_asset_registry_binding_and_report_hash_reject_registry_drift(self):
        changed_registry = copy.deepcopy(self.asset_registry)
        changed_registry["candidates"]["unreviewed_candidate"] = {}
        report = asset.audit(
            self.spec, self.catalog, asset_registry=changed_registry
        )
        self.assertFalse(report["schema_valid"])
        self.assertEqual(
            report["asset_registry_sha256"],
            asset._document_sha256(changed_registry),
        )

        changed_registry = copy.deepcopy(self.asset_registry)
        changed_registry["derived_variants"]["legacy_casper_1914_width_scaled_1708_proxy"][
            "visual_manifest"
        ]["sha256"] = "b" * 64
        report = asset.audit(self.spec, self.catalog, asset_registry=changed_registry)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("tracked manifest SHA256 mismatch" in error for error in report["schema_errors"]))

        changed_registry = copy.deepcopy(self.asset_registry)
        changed_registry["target_hardware"]["revision"] = "1914"
        changed_spec = asset.make_spec(self.catalog, asset_registry=changed_registry)
        report = asset.audit(
            changed_spec, self.catalog, asset_registry=changed_registry
        )
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "target model/revision must match" in error
            for error in report["schema_errors"]
        ))

    def test_representative_body_and_button_joint_pass(self):
        self.set_topology([
            self.body("shell_body", "shell"),
            self.body("a_cap", "a"),
        ])
        self.set_motion_model(
            "a",
            [self.joint(
                "a_press", "prismatic", "shell_body", "a_cap",
                [("a", [[0, 0], [0.002, 1]])],
            )],
        )
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        mapping = self.spec["parts"]["a"]["motion_model"]["joints"][0]["input_mapping"]["value"]
        self.assertEqual(mapping["model"], "digital_hysteresis")
        self.assertEqual(mapping["output_kind"], "standard_channels")
        self.assertEqual(mapping["initial_state"], [0])
        self.assertEqual({tuple(item["output_state"]) for item in mapping["inverse_representatives"]}, {(0,), (1,)})

    def test_passive_joint_has_no_fabricated_actuator_limits(self):
        self.set_topology([self.body("shell_body"), self.body("a_cap")])
        joint = self.joint(
            "a_press", "prismatic", "shell_body", "a_cap",
            [("a", [[0, 0], [0.002, 1]])],
        )
        self.set_motion_model("a", [joint])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertEqual(joint["actuation_mode"]["value"], "passive")
        self.assertEqual(joint["actuator_effort_limit"]["status"], "intentionally_absent")
        self.assertEqual(joint["actuator_velocity_limit"]["status"], "intentionally_absent")

        joint["actuation_mode"] = self.evidence_field("actuated", None)
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        joint["actuator_effort_limit"] = self.evidence_field(
            1.0, asset.JOINT_UNITS["prismatic"]["actuator_effort_limit"]
        )
        joint["actuator_velocity_limit"] = self.evidence_field(
            1.0, asset.JOINT_UNITS["prismatic"]["actuator_velocity_limit"]
        )
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_digital_hysteresis_thresholds_state_and_representatives_are_strict(self):
        mutations = (
            lambda mapping: mapping["effects"][0].update(press_threshold=0.0004, release_threshold=0.001),
            lambda mapping: mapping.update(initial_state=[1]),
            lambda mapping: mapping.update(inverse_policy="unique_inverse"),
            lambda mapping: mapping["inverse_representatives"][1].update(coordinate=0.0001),
            lambda mapping: mapping.update(output_kind="physical_event"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("shell_body"), self.body("a_cap")])
                joint = self.joint(
                    "a_press", "prismatic", "shell_body", "a_cap",
                    [("a", [[0, 0], [0.002, 1]])],
                )
                mutate(joint["input_mapping"]["value"])
                self.set_motion_model("a", [joint])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_analog_trigger_does_not_use_digital_switch_semantics(self):
        self.set_topology([self.body("shell_body"), self.body("trigger_cap")])
        joint = self.joint(
            "trigger_pull", "prismatic", "shell_body", "trigger_cap",
            [("left_trigger", [[0, 0], [0.002, 1]])],
        )
        self.set_motion_model("left_trigger", [joint])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertEqual(joint["input_mapping"]["value"]["model"], "analog_monotone")

    def test_physical_body_may_explicitly_omit_visual_and_collision_but_not_leave_them_unknown(self):
        body = self.body("fixture")
        self.set_topology([body])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertEqual(body["visual_geometry"]["status"], "intentionally_absent")
        self.assertEqual(body["collision_geometry"]["status"], "intentionally_absent")

        body["visual_geometry"] = asset.unknown("visual_geometry")
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("modeled topology cannot contain unresolved" in error for error in report["schema_errors"]))

    def test_virtual_intermediate_frame_has_no_fake_mass_geometry_or_contact(self):
        virtual = self.virtual_body("gimbal_frame", "left_stick")
        self.set_topology([
            self.body("shell_body", "shell"),
            virtual,
            self.body("stick_cap", "left_stick"),
        ])
        joints = [
            self.joint(
                "left_tilt_x", "revolute", "shell_body", "gimbal_frame",
                [("lx", [[-0.2, -1], [0, 0], [0.2, 1]])],
            ),
            self.joint(
                "left_tilt_y", "revolute", "gimbal_frame", "stick_cap",
                [("ly", [[-0.2, -1], [0, 0], [0.2, 1]])],
            ),
        ]
        self.set_motion_model("left_stick", joints, status="partial")
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertTrue(all(
            virtual[key]["status"] == "intentionally_absent"
            for key in asset.BODY_PROPERTY_FIELDS
        ))

        virtual["mass"] = self.evidence_field(1e-9, "kg")
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("never synthesize" in error for error in report["schema_errors"]))

    def test_stick_supports_serial_tilt_x_tilt_y_and_click_graph(self):
        self.set_topology([
            self.body("shell_body", "shell"),
            self.virtual_body("left_gimbal_x", "left_stick"),
            self.virtual_body("left_gimbal_y", "left_stick"),
            self.body("left_cap", "left_stick"),
        ])
        joints = [
            self.joint(
                "left_tilt_x", "revolute", "shell_body", "left_gimbal_x",
                [("lx", [[-0.2, -1], [0, 0], [0.2, 1]])],
            ),
            self.joint(
                "left_tilt_y", "revolute", "left_gimbal_x", "left_gimbal_y",
                [("ly", [[-0.2, -1], [0, 0], [0.2, 1]])],
            ),
            self.joint(
                "left_click", "prismatic", "left_gimbal_y", "left_cap",
                [("left_stick_click", [[0, 0], [0.002, 1]])],
            ),
        ]
        self.set_motion_model("left_stick", joints)
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_dpad_rocker_joints_can_drive_coupled_opposite_effects(self):
        self.set_topology([
            self.body("shell_body", "shell"),
            self.body("dpad_gimbal", "dpad"),
            self.body("dpad_cap", "dpad"),
        ])
        horizontal = self.joint(
            "dpad_horizontal", "revolute", "shell_body", "dpad_gimbal",
            [
                ("dpad_left", [[-0.2, 1], [0, 0], [0.2, 0]]),
                ("dpad_right", [[-0.2, 0], [0, 0], [0.2, 1]]),
            ],
        )
        vertical = self.joint(
            "dpad_vertical", "revolute", "dpad_gimbal", "dpad_cap",
            [
                ("dpad_up", [[-0.2, 1], [0, 0], [0.2, 0]]),
                ("dpad_down", [[-0.2, 0], [0, 0], [0.2, 1]]),
            ],
        )
        self.set_motion_model("dpad", [horizontal, vertical])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_stick_polar_envelope_rejects_rectangular_corner(self):
        constraint = self.polar_constraint()
        self.set_topology([
            self.body("shell_body", "shell"),
            self.virtual_body("left_gimbal_x", "left_stick"),
            self.virtual_body("left_gimbal_y", "left_stick"),
            self.body("left_cap", "left_stick"),
        ], constraints=[constraint])
        joints = [
            self.joint(
                "left_tilt_x", "revolute", "shell_body", "left_gimbal_x",
                [("lx", [[-0.2, -1], [0, 0], [0.2, 1]])],
            ),
            self.joint(
                "left_tilt_y", "revolute", "left_gimbal_x", "left_gimbal_y",
                [("ly", [[-0.2, -1], [0, 0], [0.2, 1]])],
            ),
            self.joint(
                "left_click", "prismatic", "left_gimbal_y", "left_cap",
                [("left_stick_click", [[0, 0], [0.002, 1]])],
            ),
        ]
        model = self.set_motion_model("left_stick", joints)
        model["configuration_domain"] = self.constrained_domain(
            constraint["id"],
            {"left_tilt_x": 0.0, "left_tilt_y": 0.0, "left_click": 0.0},
            independent_joint_ids=["left_click"],
        )
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertTrue(asset.configuration_satisfies_constraint(constraint, [0.2, 0.0]))
        self.assertFalse(asset.configuration_satisfies_constraint(constraint, [0.2, 0.2]))

        domain = model["configuration_domain"]
        domain["independent_joint_ids"] = []
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("cover every owned joint" in error for error in report["schema_errors"]))
        domain["independent_joint_ids"] = ["left_click"]
        domain["neutral_configuration"]["left_tilt_x"] = 0.1
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("disagrees with joint equilibrium" in error for error in report["schema_errors"]))
        domain["neutral_configuration"]["left_tilt_x"] = 0.0

        constraint["samples"][1][1] = 0.3
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("boundary exceeds" in error for error in report["schema_errors"]))

    def test_dpad_linear_inequality_domain_is_explicit_and_evaluable(self):
        constraint = {
            "id": "dpad_diamond",
            "type": "linear_inequality_set",
            "joint_ids": ["dpad_horizontal", "dpad_vertical"],
            "frame": "joint_coordinate_space",
            "coordinate_units": ["rad", "rad"],
            "bound_unit": "rad",
            "inequalities": [
                {"coefficients": [1, 1], "operator": "<=", "bound": 0.2},
                {"coefficients": [1, -1], "operator": "<=", "bound": 0.2},
                {"coefficients": [-1, 1], "operator": "<=", "bound": 0.2},
                {"coefficients": [-1, -1], "operator": "<=", "bound": 0.2},
            ],
            "numeric_payload_evidence": self.evidence_field(
                {"inequalities": [
                    {"coefficients": [1, 1], "operator": "<=", "bound": 0.2},
                    {"coefficients": [1, -1], "operator": "<=", "bound": 0.2},
                    {"coefficients": [-1, 1], "operator": "<=", "bound": 0.2},
                    {"coefficients": [-1, -1], "operator": "<=", "bound": 0.2},
                ]},
                "typed_by_constraint_schema",
            ),
            "evidence": ["xbox_visual"],
            "harness": self.schema_harness(
                "EvidenceTests.test_dpad_linear_inequality_domain_is_explicit_and_evaluable"
            ),
            "applicability": "Synthetic D-pad domain; not an Xbox physical claim.",
        }
        self.set_topology([
            self.body("shell_body", "shell"),
            self.virtual_body("dpad_gimbal", "dpad"),
            self.body("dpad_cap", "dpad"),
        ], constraints=[constraint])
        horizontal = self.joint(
            "dpad_horizontal", "revolute", "shell_body", "dpad_gimbal",
            [
                ("dpad_left", [[-0.2, 1], [0, 0], [0.2, 0]]),
                ("dpad_right", [[-0.2, 0], [0, 0], [0.2, 1]]),
            ],
        )
        vertical = self.joint(
            "dpad_vertical", "revolute", "dpad_gimbal", "dpad_cap",
            [
                ("dpad_up", [[-0.2, 1], [0, 0], [0.2, 0]]),
                ("dpad_down", [[-0.2, 0], [0, 0], [0.2, 1]]),
            ],
        )
        model = self.set_motion_model("dpad", [horizontal, vertical])
        model["configuration_domain"] = self.constrained_domain(
            constraint["id"],
            {"dpad_horizontal": 0.0, "dpad_vertical": 0.0},
        )
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertTrue(asset.configuration_satisfies_constraint(constraint, [0.1, 0.1]))
        self.assertFalse(asset.configuration_satisfies_constraint(constraint, [0.2, 0.2]))

        constraint["inequalities"].append(
            {"coefficients": [1, 0], "operator": "<=", "bound": -0.1}
        )
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("no feasibility witness" in error for error in report["schema_errors"]))

    def test_multi_joint_model_cannot_leave_configuration_domain_unknown(self):
        self.set_topology([
            self.body("root"), self.virtual_body("middle"), self.body("cap")
        ])
        joints = [
            self.joint("first", "revolute", "root", "middle", [("lx", [[-0.2, -1], [0, 0], [0.2, 1]])]),
            self.joint("second", "revolute", "middle", "cap", [("ly", [[-0.2, -1], [0, 0], [0.2, 1]])]),
        ]
        model = self.set_motion_model("left_stick", joints, status="partial")
        model["configuration_domain"] = copy.deepcopy(
            asset._unknown_motion_model("left_stick")["configuration_domain"]
        )
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

        model["status"] = "modeled"
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("multi-joint modeled" in error for error in report["schema_errors"]))

    def test_shared_body_cross_control_effects_are_not_implicitly_aggregated(self):
        self.set_topology([
            self.body("shell_body", "shell"),
            self.body("shared_bumper", "shared"),
        ])
        joint = self.joint(
            "bumper_rocker", "revolute", "shell_body", "shared_bumper",
            [
                ("left_shoulder", [[-0.2, 1], [0, 0], [0.2, 0]]),
                ("right_shoulder", [[-0.2, 0], [0, 0], [0.2, 1]]),
            ],
        )
        self.set_motion_model("left_shoulder", [joint])
        self.set_motion_model("right_shoulder", [])
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "channels owned by another logical control" in error
            for error in report["schema_errors"]
        ))

    def test_global_body_and_joint_ids_are_unique_and_references_resolve(self):
        duplicate = self.body("same")
        self.set_topology([duplicate, copy.deepcopy(duplicate)])
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])
        for missing_id in ("missing_parent", "missing_child"):
            self.spec = asset.make_spec(self.catalog)
            self.set_topology([self.body("shell_body"), self.body("a_cap")])
            parent = missing_id if "parent" in missing_id else "shell_body"
            child = missing_id if "child" in missing_id else "a_cap"
            joint = self.joint("a_press", "prismatic", parent, child, [("a", [[0, 0], [0.002, 1]])])
            self.set_motion_model("a", [joint])
            self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_duplicate_channel_mappings_are_rejected_without_aggregation_schema(self):
        self.set_topology([
            self.body("shell_body"), self.body("a_cap_1"), self.body("a_cap_2")
        ])
        joints = [
            self.joint("a_press_1", "prismatic", "shell_body", "a_cap_1", [("a", [[0, 0], [0.002, 1]])]),
            self.joint("a_press_2", "prismatic", "shell_body", "a_cap_2", [("a", [[0, 0], [0.002, 1]])]),
        ]
        self.set_motion_model("a", joints)
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_controls_cannot_swap_channels_even_when_global_channel_counts_match(self):
        self.set_topology([
            self.body("shell_body", "shell"),
            self.body("a_cap", "a"),
            self.body("b_cap", "b"),
        ])
        self.set_motion_model("a", [self.joint(
            "a_press", "prismatic", "shell_body", "a_cap",
            [("b", [[0, 0], [0.002, 1]])],
        )])
        self.set_motion_model("b", [self.joint(
            "b_press", "prismatic", "shell_body", "b_cap",
            [("a", [[0, 0], [0.002, 1]])],
        )])
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "channels owned by another logical control" in error
            for error in report["schema_errors"]
        ))

    def test_joint_units_are_cross_checked_by_joint_type(self):
        for key in (
            "joint_limits", "actuator_effort_limit", "actuator_velocity_limit", "restoring_curve",
            "damping", "joint_friction", "input_mapping",
        ):
            with self.subTest(key=key):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("shell_body"), self.body("a_cap")])
                joint = self.joint("a_press", "prismatic", "shell_body", "a_cap", [("a", [[0, 0], [0.002, 1]])])
                joint[key]["unit"] = "bananas"
                self.set_motion_model("a", [joint])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_continuous_joint_uses_explicit_unbounded_limits(self):
        self.set_topology([self.body("root"), self.body("guide_ring")])
        joint = self.joint(
            "guide_rotation", "continuous", "root", "guide_ring",
            [("guide", [[-0.2, 0], [0.2, 1]])],
        )
        self.set_motion_model("guide", [joint])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        joint["joint_limits"]["value"] = {"lower": -1, "upper": 1}
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_joint_values_reject_bananas_and_invalid_ranges(self):
        cases = (
            ("joint_origin", {"xyz": [0, 0, 0], "rpy": [0, 0, 0]}),
            ("joint_axis", [0, 0, 1]),
            ("joint_axis", "bananas"),
            ("joint_limits", {"lower": 1, "upper": -1}),
            ("joint_limits", {"lower": 0, "upper": 1, "effort": 2}),
            ("actuator_effort_limit", 0),
            ("actuator_velocity_limit", "bananas"),
            ("restoring_curve", [[0, 0], [0, 1]]),
            ("damping", "bananas"),
            ("joint_friction", -1),
        )
        for key, bad_value in cases:
            with self.subTest(key=key):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("shell_body"), self.body("a_cap")])
                joint = self.joint("a_press", "prismatic", "shell_body", "a_cap", [("a", [[0, 0], [0.002, 1]])])
                joint[key]["value"] = bad_value
                self.set_motion_model("a", [joint])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_modeled_motion_rejects_unresolved_joint_fields(self):
        self.set_topology([self.body("shell_body"), self.body("a_cap")])
        joint = self.joint(
            "a_press", "prismatic", "shell_body", "a_cap",
            [("a", [[0, 0], [0.002, 1]])],
        )
        joint["damping"] = asset.unknown(
            "damping", asset.JOINT_UNITS["prismatic"]["damping"]
        )
        self.set_motion_model("a", [joint])
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_restoring_and_mapping_curve_coordinates_stay_inside_limits(self):
        for key in ("restoring_curve", "input_mapping"):
            with self.subTest(key=key):
                self.spec = asset.make_spec(self.catalog)
                component = "a" if key == "restoring_curve" else "left_trigger"
                channel = "a" if key == "restoring_curve" else "left_trigger"
                self.set_topology([self.body("shell_body"), self.body("control_cap")])
                joint = self.joint(
                    "control_press", "prismatic", "shell_body", "control_cap",
                    [(channel, [[0, 0], [0.002, 1]])],
                )
                if key == "restoring_curve":
                    joint[key]["value"] = [[0, 0], [0.003, 1]]
                else:
                    joint[key]["value"]["effects"][0]["curve"] = [[0, 0], [0.003, 1]]
                self.set_motion_model(component, [joint])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_restoring_curve_has_explicit_stable_sign_and_hysteresis_branches(self):
        self.set_topology([self.body("shell_body"), self.body("a_cap")])
        joint = self.joint(
            "a_press", "prismatic", "shell_body", "a_cap",
            [("a", [[0, 0], [0.002, 1]])],
        )
        curve = joint["restoring_curve"]["value"]
        curve.update(
            model="loading_release_hysteresis",
            branches={
                "loading": [[0, 0], [0.002, -0.2]],
                "release": [[0, 0], [0.002, -0.1]],
            },
            branch_selection="loading_when_abs_displacement_increases_release_when_it_decreases",
            limitation="Synthetic loading/release branches; schema test only.",
        )
        self.set_motion_model("a", [joint])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

        active_hysteresis = copy.deepcopy(self.spec)
        branches = active_hysteresis["parts"]["a"]["motion_model"]["joints"][0][
            "restoring_curve"
        ]["value"]["branches"]
        branches["loading"][-1][1], branches["release"][-1][1] = (
            branches["release"][-1][1], branches["loading"][-1][1]
        )
        report = asset.audit(active_hysteresis, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "injects positive net work" in error for error in report["schema_errors"]
        ))

        crossing = copy.deepcopy(self.spec)
        crossing_branches = crossing["parts"]["a"]["motion_model"]["joints"][0][
            "restoring_curve"
        ]["value"]["branches"]
        crossing_branches["loading"] = [
            [0, 0], [0.001, -0.1], [0.002, -10.0]
        ]
        crossing_branches["release"] = [
            [0, 0], [0.001, -1.0], [0.002, -1.0]
        ]
        report = asset.audit(crossing, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "injects positive net work" in error for error in report["schema_errors"]
        ))

        joint["restoring_curve"]["value"]["branches"]["loading"][-1][1] = 0.2
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("oppose displacement" in error for error in report["schema_errors"]))

    def test_restoring_curve_domain_equilibrium_and_branch_policy_are_closed(self):
        mutations = (
            lambda curve: curve.update(interpolation="cubic"),
            lambda curve: curve.update(outside_domain="clamp"),
            lambda curve: curve.update(equilibrium_coordinate=0.001),
            lambda curve: curve["branches"].update(single=[[0.0001, -0.01], [0.002, -0.1]]),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("shell_body"), self.body("a_cap")])
                joint = self.joint(
                    "a_press", "prismatic", "shell_body", "a_cap",
                    [("a", [[0, 0], [0.002, 1]])],
                )
                mutate(joint["restoring_curve"]["value"])
                self.set_motion_model("a", [joint])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_malformed_restoring_branch_is_a_schema_error_not_an_audit_crash(self):
        self.set_topology([self.body("shell_body"), self.body("a_cap")])
        joint = self.joint(
            "a_press", "prismatic", "shell_body", "a_cap",
            [("a", [[0, 0], [0.002, 1]])],
        )
        joint["restoring_curve"]["value"]["branches"]["single"] = 42
        self.set_motion_model("a", [joint])
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "branches.single must contain at least two finite" in error
            for error in report["schema_errors"]
        ))

    def test_input_mapping_is_monotone_full_range_invertible_and_neutral_aligned(self):
        def nonmonotone(mapping):
            mapping["effects"][0]["curve"] = [[0, 0], [0.001, 1], [0.002, 0]]

        def incomplete(mapping):
            mapping["effects"][0]["curve"] = [[0, 0], [0.002, 0.8]]

        def bad_neutral(mapping):
            mapping["neutral_coordinate"] = 0.001

        mutations = (
            nonmonotone,
            incomplete,
            bad_neutral,
            lambda mapping: mapping.update(interpolation="cubic"),
            lambda mapping: mapping.update(outside_domain="clamp"),
            lambda mapping: mapping.update(inverse_policy="first_branch"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("shell_body"), self.body("trigger_cap")])
                joint = self.joint(
                    "trigger_press", "prismatic", "shell_body", "trigger_cap",
                    [("left_trigger", [[0, 0], [0.002, 1]])],
                )
                mutate(joint["input_mapping"]["value"])
                self.set_motion_model("left_trigger", [joint])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_coupled_effect_tuple_rejects_a_shared_flat_interval(self):
        self.set_topology([self.body("root"), self.body("stick_cap")])
        joint = self.joint(
            "stick_projection", "revolute", "root", "stick_cap",
            [
                ("lx", [[-0.2, -1], [-0.1, 0], [0, 0], [0.1, 0], [0.2, 1]]),
                ("ly", [[-0.2, -1], [-0.1, 0], [0, 0], [0.1, 0], [0.2, 1]]),
            ],
        )
        self.set_motion_model("left_stick", [joint], status="partial")
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("tuple is not invertible" in error for error in report["schema_errors"]))

    def test_partial_graph_rejects_cycle_and_multiple_parents(self):
        for topology in ("cycle", "multiple_parents"):
            with self.subTest(topology=topology):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology(
                    [self.body("root"), self.body("middle"), self.body("child")],
                    status="partial",
                )
                if topology == "cycle":
                    first = self.joint("first", "prismatic", "root", "middle", [("a", [[0, 0], [0.002, 1]])])
                    second = self.joint("second", "prismatic", "middle", "root", [("b", [[0, 0], [0.002, 1]])])
                else:
                    first = self.joint("first", "prismatic", "root", "child", [("a", [[0, 0], [0.002, 1]])])
                    second = self.joint("second", "prismatic", "middle", "child", [("b", [[0, 0], [0.002, 1]])])
                self.set_motion_model("a", [first], status="partial")
                self.set_motion_model("b", [second], status="partial")
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_modeled_body_graph_must_be_one_connected_tree(self):
        self.set_topology([
            self.body("root"), self.body("a_cap"), self.body("unused_body")
        ])
        joint = self.joint(
            "a_press", "prismatic", "root", "a_cap",
            [("a", [[0, 0], [0.002, 1]])],
        )
        self.set_motion_model("a", [joint])
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_unknown_channels_are_rejected(self):
        self.set_topology([self.body("shell_body"), self.body("a_cap")])
        joint = self.joint(
            "a_press", "prismatic", "shell_body", "a_cap",
            [("not_a_channel", [[0, 0], [0.002, 1]])],
        )
        self.set_motion_model("a", [joint])
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_canonical_21_channel_definition_is_strict(self):
        channels = self.spec["input_schema"]["channels"]
        self.assertEqual(len(channels), 21)
        self.assertEqual([entry["name"] for entry in channels], list(asset.CANONICAL_CHANNELS))
        channels[0]["name"] = "unknown_axis"
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_pair_is_physical_only_not_a_twenty_second_channel(self):
        self.assertIn("pair", self.spec["parts"])
        pair = self.spec["parts"]["pair"]["motion_model"]
        self.assertTrue(pair["physical_only"])
        self.assertEqual(pair["required_control_effects"], [])
        self.assertNotIn("pair", asset.CANONICAL_CHANNELS)
        self.assertEqual(len(asset.CANONICAL_CHANNELS), 21)
        self.assertIn("Connect", self.spec["physical_only_controls"]["pair"]["aliases"])

    def test_pair_joint_can_be_modeled_without_creating_a_standard_channel(self):
        self.set_topology([self.body("shell_body"), self.body("pair_cap", "pair")])
        joint = self.joint(
            "pair_press", "prismatic", "shell_body", "pair_cap", []
        )
        joint["input_mapping"]["unit"] = "m->physical_event"
        self.set_motion_model("pair", [joint])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertEqual(len(asset.CANONICAL_CHANNELS), 21)
        mapping = joint["input_mapping"]["value"]
        self.assertEqual(mapping["output_kind"], "physical_event")
        self.assertEqual(mapping["effects"], [])
        self.assertEqual(mapping["physical_event"]["name"], "pair_bind_connect")

    def test_standard_control_cannot_use_an_empty_physical_only_mapping(self):
        self.set_topology([self.body("shell_body"), self.body("a_cap", "a")])
        joint = self.joint("a_press", "prismatic", "shell_body", "a_cap", [])
        self.set_motion_model("a", [joint])
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def mesh_collider(
        self, filename, sha256, *, mobility="static", query_only=False,
        actor_kind=None,
    ):
        if actor_kind is None:
            actor_kind = {
                "static": "rigid_static",
                "kinematic": "rigid_kinematic",
                "dynamic": "rigid_dynamic",
            }[mobility]
        dynamic_simulation = mobility == "dynamic" and not query_only
        return {
            "type": "mesh",
            "frame": "body",
            "pose": self.pose(),
            "pose_unit": "m,rad",
            **self.collider_common(),
            "file": filename,
            "sha256": sha256,
            "meters_per_native_unit": [1, 1, 1],
            "meters_per_native_unit_unit": "m/native_unit",
            "backend_shape": {
                "engine": "physx_5",
                "simulation_role": "query_only" if query_only else "simulation_and_query",
                "actor_kind": actor_kind,
                "actor_mobility": mobility,
                "cooking": "triangle_mesh_sdf" if dynamic_simulation else "triangle_mesh",
                "gpu_dynamics": dynamic_simulation,
                "sdf_artifact": (
                    {"file": "gpu_assets/collision/controller.sdf", "sha256": "b" * 64}
                    if dynamic_simulation
                    else None
                ),
            },
        }

    def test_mesh_collider_allows_off_node_file_but_reports_hash_unverified(self):
        collider = self.mesh_collider("gpu_assets/collision/controller.obj", "a" * 64)
        self.set_topology([self.body("shell_body", "shell", collider)])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertEqual(report["artifact_hash_verification"]["status"], "unverified")
        self.assertIsNone(
            report["artifact_hash_verification"]["items"][0]["exists_at_artifact_root"]
        )

    def test_local_mesh_hash_is_verified_separately_from_schema(self):
        path = ROOT / "sources/catalog.json"
        collider = self.mesh_collider(
            "sources/catalog.json", hashlib.sha256(path.read_bytes()).hexdigest()
        )
        self.set_topology([self.body("shell_body", "shell", collider)])
        report = asset.audit(self.spec, self.catalog, artifact_root=ROOT)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertEqual(report["artifact_hash_verification"]["status"], "verified")

    def test_mesh_path_sha_pose_and_scale_are_strict(self):
        valid = self.mesh_collider("gpu_assets/controller.obj", "a" * 64)
        changes = (
            {**valid, "file": "/tmp/controller.obj"},
            {**valid, "file": "../controller.obj"},
            {**valid, "file": "folder\\controller.obj"},
            {**valid, "file": "https://example/controller.obj"},
            {key: value for key, value in valid.items() if key != "sha256"},
            {**valid, "sha256": "not-a-hash"},
            {**valid, "meters_per_native_unit": [1, 0, 1]},
            {**valid, "meters_per_native_unit_unit": "1"},
            {key: value for key, value in valid.items() if key != "pose"},
        )
        for bad in changes:
            with self.subTest(bad=bad):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("shell_body", "shell", bad)])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_primitive_collider_has_explicit_body_relative_pose_and_units(self):
        bad = self.sphere_collider()
        del bad["pose"]
        self.set_topology([self.body("shell_body", "shell", bad)])
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_collider_filter_and_contact_offsets_are_required_and_consistent(self):
        valid = self.sphere_collider()
        changes = [
            {key: value for key, value in valid.items() if key != missing}
            for missing in ("collision_filter", "contact_offset", "rest_offset")
        ]
        bad_filter = copy.deepcopy(valid)
        bad_filter["collision_filter"]["word3_id"] = -1
        aliased_filter = copy.deepcopy(valid)
        aliased_filter["collision_filter"]["word3_id"] = 0x10001
        lossy_filter = copy.deepcopy(valid)
        lossy_filter["collision_filter"] = {"group": 1, "mask": 0xFFFFFFFF}
        changes.extend((
            bad_filter,
            aliased_filter,
            lossy_filter,
            {**valid, "contact_offset": 0.001, "rest_offset": 0.001},
            {**valid, "contact_offset": 0.001, "rest_offset": 0.002},
            {**valid, "contact_offset": -0.001, "rest_offset": -0.002},
            {**valid, "offset_unit": "mm"},
        ))
        for collider in changes:
            with self.subTest(collider=collider):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("shell_body", "shell", collider)])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

        zero_contact = {**valid, "contact_offset": 0.0, "rest_offset": -0.001}
        self.spec = asset.make_spec(self.catalog)
        self.set_topology([self.body("shell_body", "shell", zero_contact)])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_dynamic_triangle_mesh_requires_sdf_gpu_cooking_and_body_mobility(self):
        dynamic_mesh = self.mesh_collider(
            "gpu_assets/collision/controller.obj", "a" * 64, mobility="dynamic",
            actor_kind="articulation_link_nonkinematic",
        )
        self.set_topology([
            self.body("shell_body", "shell"),
            self.body("button_body", "a", dynamic_mesh),
        ])
        joint = self.joint(
            "a_press", "prismatic", "shell_body", "button_body",
            [("a", [[0, 0], [0.002, 1]])],
        )
        self.set_motion_model("a", [joint])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.assertEqual(
            {item["role"] for item in report["artifact_hash_verification"]["items"]},
            {"collision_mesh", "collision_sdf"},
        )

        for mutate in (
            lambda backend: backend.update(cooking="triangle_mesh"),
            lambda backend: backend.update(gpu_dynamics=False),
            lambda backend: backend.update(sdf_artifact=None),
            lambda backend: backend.update(actor_mobility="kinematic"),
        ):
            with self.subTest(mutate=mutate):
                broken = copy.deepcopy(self.spec)
                backend = broken["physical_topology"]["bodies"][1]["collision_geometry"]["value"]["backend_shape"]
                mutate(backend)
                self.assertFalse(asset.audit(broken, self.catalog)["schema_valid"])

    def test_query_only_dynamic_triangle_mesh_does_not_fabricate_sdf(self):
        collider = self.mesh_collider(
            "gpu_assets/collision/controller.obj", "a" * 64,
            mobility="dynamic", query_only=True,
            actor_kind="articulation_link_nonkinematic",
        )
        self.set_topology([
            self.body("shell_body", "shell"),
            self.body("query_body", "a", collider),
        ])
        joint = self.joint(
            "a_press", "prismatic", "shell_body", "query_body",
            [("a", [[0, 0], [0.002, 1]])],
        )
        self.set_motion_model("a", [joint])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_convex_mesh_requires_explicit_physx_cooking(self):
        collider = self.mesh_collider(
            "gpu_assets/collision/controller_convex.obj", "a" * 64
        )
        collider["type"] = "convex_mesh"
        collider["backend_shape"]["cooking"] = "convex_hull"
        self.set_topology([self.body("shell_body", "shell", collider)])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

        for mutate in (
            lambda shape: shape.pop("backend_shape"),
            lambda shape: shape["backend_shape"].update(cooking="triangle_mesh"),
            lambda shape: shape["backend_shape"].update(sdf_artifact={
                "file": "gpu_assets/collision/fake.sdf", "sha256": "b" * 64,
            }),
        ):
            with self.subTest(mutate=mutate):
                broken = copy.deepcopy(collider)
                mutate(broken)
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("shell_body", "shell", broken)])
                self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_self_collision_policy_must_match_four_word_shape_filters(self):
        self.set_topology([
            self.body("shell_body", "shell", self.sphere_collider()),
            self.body("middle_link", "a"),
            self.body("a_cap", "a", self.sphere_collider()),
        ])
        self.set_motion_model("a", [self.joint(
            "a_press", "prismatic", "shell_body", "middle_link",
            [("a", [[0, 0], [0.002, 1]])],
        )])
        self.set_motion_model("b", [self.joint(
            "b_press", "prismatic", "middle_link", "a_cap",
            [("b", [[0, 0], [0.002, 1]])],
        )])
        policy = self.spec["physical_topology"]["self_collision_policy"]
        policy["pair_overrides"] = [
            {"body_a": "shell_body", "body_b": "a_cap", "enabled": True},
        ]
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

        blocked = copy.deepcopy(self.spec)
        second_filter = blocked["physical_topology"]["bodies"][2][
            "collision_geometry"
        ]["value"]["collision_filter"]
        second_filter["word0_contact_type"] = 0
        second_filter["word1_contact_affinity"] = 0
        report = asset.audit(blocked, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "contradicts the effective backend result" in error
            for error in report["schema_errors"]
        ))

        disabled_but_allowed = copy.deepcopy(self.spec)
        disabled_but_allowed["physical_topology"]["self_collision_policy"][
            "pair_overrides"
        ][0]["enabled"] = False
        self.assertFalse(asset.audit(disabled_but_allowed, self.catalog)["schema_valid"])

        blocked["physical_topology"]["self_collision_policy"]["pair_overrides"][0][
            "enabled"
        ] = False
        report = asset.audit(blocked, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_physx_adjacent_articulation_links_are_unconditionally_noncolliding(self):
        self.set_topology([
            self.body("shell_body", "shell", self.sphere_collider()),
            self.body("a_cap", "a", self.sphere_collider()),
        ])
        self.set_motion_model("a", [self.joint(
            "a_press", "prismatic", "shell_body", "a_cap",
            [("a", [[0, 0], [0.002, 1]])],
        )])
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

        self.spec["physical_topology"]["self_collision_policy"]["default"] = "enabled"
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "direct parent-child pair" in error
            and "cannot be enabled" in error
            for error in report["schema_errors"]
        ))

    def test_query_only_shape_cannot_satisfy_enabled_self_collision(self):
        query_only_tip = self.mesh_collider(
            "gpu_assets/collision/query_only_tip.obj", "a" * 64,
            mobility="dynamic", query_only=True,
            actor_kind="articulation_link_nonkinematic",
        )
        self.set_topology([
            self.body("shell_body", "shell", self.sphere_collider()),
            self.body("middle_link", "a"),
            self.body("tip_body", "b", query_only_tip),
        ])
        self.set_motion_model("a", [self.joint(
            "a_press", "prismatic", "shell_body", "middle_link",
            [("a", [[0, 0], [0.002, 1]])],
        )])
        self.set_motion_model("b", [self.joint(
            "b_press", "prismatic", "middle_link", "tip_body",
            [("b", [[0, 0], [0.002, 1]])],
        )])
        policy = self.spec["physical_topology"]["self_collision_policy"]
        policy["pair_overrides"] = [
            {"body_a": "shell_body", "body_b": "tip_body", "enabled": True},
        ]
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "contradicts the effective backend result" in error
            and "effective_allow=False" in error
            for error in report["schema_errors"]
        ))

        policy["pair_overrides"][0]["enabled"] = False
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_fixed_base_articulation_root_is_not_a_rigid_static_actor(self):
        static_root_mesh = self.mesh_collider(
            "gpu_assets/collision/controller.obj", "a" * 64,
        )
        self.set_topology([
            self.body("shell_body", "shell", static_root_mesh),
            self.body("a_cap", "a"),
        ])
        self.set_motion_model("a", [self.joint(
            "a_press", "prismatic", "shell_body", "a_cap",
            [("a", [[0, 0], [0.002, 1]])],
        )])
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any(
            "fixed articulation root is not a rigid static actor" in error
            for error in report["schema_errors"]
        ))

        articulation_root_mesh = self.mesh_collider(
            "gpu_assets/collision/controller.obj", "a" * 64,
            mobility="dynamic", actor_kind="articulation_link_nonkinematic",
        )
        self.spec["physical_topology"]["bodies"][0] = self.body(
            "shell_body", "shell", articulation_root_mesh,
        )
        report = asset.audit(self.spec, self.catalog)
        self.assertTrue(report["schema_valid"], report["schema_errors"])

    def test_modeled_topology_requires_root_attachment_and_self_collision_policy(self):
        for field in ("root_attachment", "self_collision_policy"):
            with self.subTest(field=field):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("shell_body", "shell")])
                self.spec["physical_topology"][field] = copy.deepcopy(
                    asset._unknown_physical_topology()[field]
                )
                report = asset.audit(self.spec, self.catalog)
                self.assertFalse(report["schema_valid"])
                self.assertTrue(any("modeled topology requires explicit" in error for error in report["schema_errors"]))

    def test_self_collision_overrides_are_unique_valid_body_pairs(self):
        self.set_topology([self.body("root"), self.body("cap")])
        joint = self.joint(
            "a_press", "prismatic", "root", "cap",
            [("a", [[0, 0], [0.002, 1]])],
        )
        self.set_motion_model("a", [joint])
        policy = self.spec["physical_topology"]["self_collision_policy"]
        policy["pair_overrides"] = [
            {"body_a": "root", "body_b": "cap", "enabled": True},
            {"body_a": "cap", "body_b": "root", "enabled": False},
        ]
        report = asset.audit(self.spec, self.catalog)
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("duplicate body pair" in error for error in report["schema_errors"]))

    def test_box_cylinder_and_capsule_dimensions_have_explicit_semantics(self):
        base = {
            "frame": "body", "pose": self.pose(), "pose_unit": "m,rad",
            **self.collider_common(),
        }
        valid = (
            {**base, "type": "box", "size": [0.1, 0.2, 0.3], "size_unit": "m", "size_semantics": "full_extents"},
            {**base, "type": "cylinder", "radius": 0.01, "height": 0.02, "length_unit": "m", "axis": "z", "height_semantics": "full_length"},
            {**base, "type": "capsule", "radius": 0.01, "height": 0.02, "length_unit": "m", "axis": "x", "height_semantics": "cylindrical_section_excluding_hemispheres"},
        )
        for collider in valid:
            with self.subTest(kind=collider["type"]):
                self.spec = asset.make_spec(self.catalog)
                self.set_topology([self.body("fixture", collider=collider)])
                report = asset.audit(self.spec, self.catalog)
                self.assertTrue(report["schema_valid"], report["schema_errors"])
        self.spec = asset.make_spec(self.catalog)
        ambiguous = copy.deepcopy(valid[2])
        ambiguous["height_semantics"] = "total_maybe"
        self.set_topology([self.body("fixture", collider=ambiguous)])
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

    def test_rpy_handedness_order_and_axis_frame_are_canonical(self):
        changed = copy.deepcopy(self.spec)
        changed["frame_convention"]["rotation_representation"] = "intrinsic_zyx"
        self.assertFalse(asset.audit(changed, self.catalog)["schema_valid"])
        changed = copy.deepcopy(self.spec)
        changed["frame_convention"]["handedness"] = "left_handed"
        self.assertFalse(asset.audit(changed, self.catalog)["schema_valid"])

    def test_fake_reference_and_unit_mismatch_fail(self):
        body = self.body("fixture")
        body["mass"]["evidence"] = ["nonexistent"]
        body["mass"]["unit"] = "g"
        self.set_topology([body])
        self.assertFalse(asset.audit(self.spec, self.catalog)["schema_valid"])

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
