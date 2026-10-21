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


from xbox_gamepad_physics.builders.asset_spec import (
    ASSET_REGISTRY_PATH, SCHEMA_VERSION, CONTROL_EFFECTS, UNRESOLVED_PARAMETERS,
    W3C_BROWSER_CHANNELS, W3C_BROWSER_CHANNEL_DEFINITIONS,
)
REPORT_SCHEMA_VERSION = 4


def load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _expected_channels():
    return [
        {
            "name": name,
            "kind": kind,
            "tensor_index": tensor_index,
            "standard_index": standard_index,
            "range": list(value_range),
        }
        for name, kind, tensor_index, standard_index, value_range
        in W3C_BROWSER_CHANNEL_DEFINITIONS
    ]


def _audit_registry_state(registry, errors):
    if registry.get("registry_role") != "canonical_status_authority":
        errors.append("asset registry is not the canonical status authority")
    target = registry.get("target_hardware")
    if not isinstance(target, dict) or target.get("model") != "Xbox One S":
        errors.append("asset registry target must remain Xbox One S")
    primary = registry.get("primary_appearance_candidate_id")
    if registry.get("approved_target_appearance_candidate_id") != primary:
        errors.append("the primary Xbox One S appearance must remain owner-approved")
    if registry.get("approved_metric_geometry_variant_id") is not None:
        errors.append(
            "metric geometry cannot be approved before dimensions are verified"
        )

    for collection_name in ("candidates", "derived_variants"):
        collection = registry.get(collection_name, {})
        if not isinstance(collection, dict):
            errors.append(f"asset registry {collection_name} must be an object")
            continue
        for candidate_id, record in collection.items():
            if not isinstance(record, dict):
                errors.append(f"asset registry record {candidate_id} must be an object")
                continue
            approval = record.get("metric_geometry_approval")
            if isinstance(approval, dict) and approval.get("approved") is not False:
                errors.append(
                    f"unmeasured candidate {candidate_id} cannot be metric-geometry-approved"
                )
            if record.get("approved_for_contact_or_training") is True:
                errors.append(
                    f"unverified candidate {candidate_id} cannot be used for contact or training"
                )

    physical = registry.get("physical_asset")
    if not isinstance(physical, dict):
        errors.append("asset registry physical_asset must be an object")
    elif any(
        (
            physical.get("collision_asset") is not None,
            physical.get("simulator_asset") is not None,
            physical.get("meters_per_native_unit") is not None,
            physical.get("contact_dynamics_validated") is not False,
        )
    ):
        errors.append("asset registry currently overstates physical readiness")


def audit(spec, catalog, artifact_root=None, asset_registry=None):
    """Validate only current-stage facts and external identity boundaries."""
    del artifact_root  # No canonical physical artifacts exist yet.
    registry = asset_registry if asset_registry is not None else json.loads(ASSET_REGISTRY_PATH.read_text())
    errors = []

    if not isinstance(spec, dict):
        errors.append("spec root must be an object")
        spec = {}
    if spec.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    catalog_sources = catalog.get("sources") if isinstance(catalog, dict) else None
    required_evidence = {
        "user_target_xbox_one_s",
        "w3c_gamepad_standard_mapping",
        "apple_1708_connect_button",
        "ifixit_1708_buttons",
    }
    if not isinstance(catalog_sources, dict):
        errors.append("reference catalog sources must be an object")
    elif missing := sorted(required_evidence - set(catalog_sources)):
        errors.append("reference catalog is missing: " + ", ".join(missing))

    binding = spec.get("asset_registry_binding")
    if not isinstance(binding, dict):
        errors.append("asset registry binding is missing")
    else:
        if binding.get("path") != "assets/asset_index.json":
            errors.append("asset registry binding path changed")
        if binding.get("registry_role") != "canonical_status_authority":
            errors.append("asset registry binding role changed")

    target_model = spec.get("target_model")
    if not isinstance(target_model, dict) or target_model.get("value") != "Xbox One S":
        errors.append("target model must remain Xbox One S")
    elif target_model.get("status") != "owner_selected_unmeasured":
        errors.append("target model must retain its owner-selected evidence status")

    input_schema = spec.get("input_schema")
    if (
        not isinstance(input_schema, dict)
        or input_schema.get("channels") != _expected_channels()
    ):
        errors.append("input schema must contain the canonical 21 channels")
    if "share" in W3C_BROWSER_CHANNELS or "pair" in W3C_BROWSER_CHANNELS:
        errors.append(
            "internal channel definitions contain a non-standard physical control"
        )

    topology = spec.get("physical_topology")
    if (
        not isinstance(topology, dict)
        or topology.get("status") != "unknown"
        or topology.get("bodies") != []
    ):
        errors.append("physical topology must remain explicitly unknown and empty")

    parts = spec.get("parts")
    if not isinstance(parts, dict) or set(parts) != set(CONTROL_EFFECTS):
        errors.append("parts must enumerate the current logical controls exactly once")
    else:
        for name, effects in CONTROL_EFFECTS.items():
            model = parts.get(name, {}).get("motion_model")
            if not isinstance(model, dict):
                errors.append(f"{name} motion model is missing")
                continue
            if model.get("status") != "unknown" or model.get("joints") != []:
                errors.append(f"{name} motion model must remain explicitly unresolved")
            represented = [
                item.get("channel")
                for item in model.get("required_control_effects", [])
                if isinstance(item, dict)
            ]
            if represented != list(effects):
                errors.append(f"{name} logical effects changed")
            if model.get("physical_only") is not (name == "pair"):
                errors.append(f"{name} physical-only flag changed")

    unresolved = spec.get("unresolved_parameters")
    unresolved_ids = []
    if not isinstance(unresolved, list):
        errors.append("unresolved_parameters must be a list")
    else:
        for entry in unresolved:
            if not isinstance(entry, dict):
                errors.append("unresolved parameter entry must be an object")
                continue
            unresolved_ids.append(entry.get("id"))
            reason = entry.get("reason")
            if (
                entry.get("value") is not None
                or not isinstance(reason, str)
                or not reason.strip()
            ):
                errors.append(
                    f"unresolved parameter {entry.get('id')!r} must remain null with a reason"
                )
        if unresolved_ids != list(UNRESOLVED_PARAMETERS):
            errors.append("unresolved parameter inventory changed")

    _audit_registry_state(registry, errors)
    blockers = [
        {"id": identifier, "detail": reason}
        for identifier, reason in UNRESOLVED_PARAMETERS.items()
    ]
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "schema_errors": errors,
        "unresolved_fields": unresolved_ids,
        "schema_valid": not errors,
        "artifact_hash_verification": {
            "status": "not_applicable",
            "checked": 0,
            "reason": "No canonical physical artifact is registered.",
        },
        "readiness_blockers": blockers,
        "readiness_reason": (
            "The current record contains no validated physical topology or contact model."
        ),
    }




class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load("references/catalog.json")
        self.registry = load("assets/asset_index.json")
        self.spec = load("specs/xbox_v1.json")

    def audit(self, specification=None, *, catalog=None, registry=None):
        return audit(
            self.spec if specification is None else specification,
            self.catalog if catalog is None else catalog,
            asset_registry=self.registry if registry is None else registry,
        )

    def test_checked_in_spec_retains_unresolved_evidence(self):
        report = self.audit()
        self.assertTrue(report["schema_valid"], report["schema_errors"])
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

    def test_missing_reference_or_invalid_registry_fails_closed(self):
        changed_catalog = copy.deepcopy(self.catalog)
        del changed_catalog["sources"]["w3c_gamepad_standard_mapping"]
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

    def test_browser_transport_has_exactly_21_owned_channels(self):
        channels = self.spec["input_schema"]["channels"]
        self.assertEqual(len(channels), 21)
        self.assertEqual(
            [channel["tensor_index"] for channel in channels], list(range(21))
        )
        self.assertEqual(
            [channel["name"] for channel in channels],
            list(asset.W3C_BROWSER_CHANNELS),
        )
        represented = [
            channel
            for control in asset.CONTROL_EFFECTS.values()
            for channel in control
        ]
        self.assertCountEqual(represented, asset.W3C_BROWSER_CHANNELS)
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
