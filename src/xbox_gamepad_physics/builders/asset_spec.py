"""Audit the Xbox asset facts that are true today.

This module deliberately does not define a future rigid-body or PhysX schema.
Those checks belong next to the first implemented simulator asset. This record
describes the browser inspection transport and unresolved physical fields; the
Python learning interface is defined separately in ``state.py``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


from .paths import DATA_ROOT, ROOT
CATALOG_PATH = ROOT / "references/catalog.json"
ASSET_REGISTRY_PATH = DATA_ROOT / "assets/asset_index.json"
SPEC_PATH = DATA_ROOT / "specs/xbox_v1.json"

SCHEMA_VERSION = 2
REPORT_SCHEMA_VERSION = 4

# Project transport order: W3C Standard Gamepad axes followed by buttons.
# The W3C specification does not itself define a tensor layout.
W3C_BROWSER_CHANNEL_DEFINITIONS = (
    ("lx", "axis", 0, 0, (-1, 1)),
    ("ly", "axis", 1, 1, (-1, 1)),
    ("rx", "axis", 2, 2, (-1, 1)),
    ("ry", "axis", 3, 3, (-1, 1)),
    ("a", "button", 4, 0, (0, 1)),
    ("b", "button", 5, 1, (0, 1)),
    ("x", "button", 6, 2, (0, 1)),
    ("y", "button", 7, 3, (0, 1)),
    ("left_shoulder", "button", 8, 4, (0, 1)),
    ("right_shoulder", "button", 9, 5, (0, 1)),
    ("left_trigger", "button", 10, 6, (0, 1)),
    ("right_trigger", "button", 11, 7, (0, 1)),
    ("view", "button", 12, 8, (0, 1)),
    ("menu", "button", 13, 9, (0, 1)),
    ("left_stick_click", "button", 14, 10, (0, 1)),
    ("right_stick_click", "button", 15, 11, (0, 1)),
    ("dpad_up", "button", 16, 12, (0, 1)),
    ("dpad_down", "button", 17, 13, (0, 1)),
    ("dpad_left", "button", 18, 14, (0, 1)),
    ("dpad_right", "button", 19, 15, (0, 1)),
    ("guide", "button", 20, 16, (0, 1)),
)
W3C_BROWSER_CHANNELS = tuple(item[0] for item in W3C_BROWSER_CHANNEL_DEFINITIONS)

CONTROL_EFFECTS = {
    "shell": (),
    "a": ("a",),
    "b": ("b",),
    "x": ("x",),
    "y": ("y",),
    "left_stick": ("lx", "ly", "left_stick_click"),
    "right_stick": ("rx", "ry", "right_stick_click"),
    "dpad": ("dpad_up", "dpad_down", "dpad_left", "dpad_right"),
    "left_shoulder": ("left_shoulder",),
    "right_shoulder": ("right_shoulder",),
    "left_trigger": ("left_trigger",),
    "right_trigger": ("right_trigger",),
    "view": ("view",),
    "menu": ("menu",),
    "guide": ("guide",),
    # Pair/Bind changes connectivity and is not a Standard Gamepad channel.
    "pair": (),
}

UNRESOLVED_PARAMETERS = {
    "metric_geometry_registration": "The selected Xbox One S mesh has no measured local-dimension registration.",
    "metric_scale": "Local dimensions have not been measured on the target controller.",
    "physical_topology": "No target rigid-body and joint graph has been established.",
    "mass_properties": "Mass, centre of mass and inertia have not been measured.",
    "collision_geometry": "No collision representation has passed contact validation.",
    "contact_materials": "Friction and restitution have not been measured.",
    "control_mechanics": "Axes, travel, force curves and restoring behaviour remain unresolved.",
    "root_attachment": "The fixture and controller attachment are not yet designed.",
}


def _load_registry(asset_registry=None):
    if asset_registry is not None:
        return asset_registry
    return json.loads(ASSET_REGISTRY_PATH.read_text())


def _channel_schema():
    return {
        "name": "w3c_browser_transport_axes_then_buttons",
        "evidence": ["w3c_gamepad_standard_mapping"],
        "channels": [
            {
                "name": name,
                "kind": kind,
                "tensor_index": tensor_index,
                "standard_index": standard_index,
                "range": list(value_range),
            }
            for name, kind, tensor_index, standard_index, value_range
            in W3C_BROWSER_CHANNEL_DEFINITIONS
        ],
        "note": (
            "This repository defines the tensor order; W3C defines the axis "
            "and button indices."
        ),
    }


def _unknown_motion_model(name):
    return {
        "status": "unknown",
        "joints": [],
        "required_control_effects": [
            {"channel": channel, "evidence": ["w3c_gamepad_standard_mapping"]}
            for channel in CONTROL_EFFECTS[name]
        ],
        "physical_only": name == "pair",
        "evidence": [],
        "reason": (
            f"No measured Xbox One S mechanism topology for {name}; "
            "visual animation is not treated as physical evidence."
        ),
    }


def make_spec(catalog, asset_registry=None):
    """Build the unresolved, evidence-bound state of the current target."""
    registry = _load_registry(asset_registry)
    target = registry.get("target_hardware", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "asset_registry_binding": {
            "path": "assets/asset_index.json",
            "registry_role": "canonical_status_authority",
        },
        "target_model": {
            "value": target.get("model"),
            "unit": None,
            "status": "owner_selected_unmeasured",
            "evidence": ["user_target_xbox_one_s"],
            "applicability": (
                "Target product and appearance identity; no physical measurement is currently available."
            ),
        },
        "status": "incomplete_not_for_dynamics_or_RL",
        "input_schema": _channel_schema(),
        "physical_only_controls": {
            "pair": {
                "aliases": ["Pair", "Bind", "Connect", "Sync"],
                "standard_gamepad_channel": None,
                "evidence": ["apple_1708_connect_button", "ifixit_1708_buttons"],
            }
        },
        "physical_topology": {
            "status": "unknown",
            "bodies": [],
            "reason": "No measured Xbox One S rigid-body graph is available.",
        },
        "parts": {
            name: {"motion_model": _unknown_motion_model(name)}
            for name in CONTROL_EFFECTS
        },
        "unresolved_parameters": [
            {"id": identifier, "value": None, "reason": reason}
            for identifier, reason in UNRESOLVED_PARAMETERS.items()
        ],
        "readiness": {
            "dynamics_ready": False,
            "contact_validated": False,
            "blockers": list(UNRESOLVED_PARAMETERS),
        },
    }


def synchronize_spec(current, catalog, asset_registry=None):
    """Return the canonical current-state document.

    Prospective physics fields are not preserved. Once a physical model exists
    it should receive its own versioned schema and tests.
    """
    del current
    return make_spec(catalog, asset_registry=asset_registry)


def validated_synchronize_spec(current, catalog, asset_registry=None):
    candidate = synchronize_spec(current, catalog, asset_registry=asset_registry)
    report = audit(candidate, catalog, asset_registry=asset_registry)
    if report["schema_errors"]:
        raise ValueError(
            "Refusing to publish an invalid specification: "
            + "; ".join(report["schema_errors"])
        )
    return candidate, report


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
    registry = _load_registry(asset_registry)
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

    if spec.get("status") != "incomplete_not_for_dynamics_or_RL":
        errors.append("spec must remain blocked from dynamics and RL")

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

    readiness = spec.get("readiness")
    if (
        not isinstance(readiness, dict)
        or readiness.get("dynamics_ready") is not False
        or readiness.get("contact_validated") is not False
    ):
        errors.append(
            "readiness must remain false until simulator/contact validation exists"
        )

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
        "dynamics_ready": False,
        "readiness_reason": (
            "The current record contains no validated physical topology or contact model."
        ),
    }


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["generate", "sync-spec", "audit", "require-dynamics"]
    )
    parser.add_argument(
        "--output", type=Path, help="write an audit outside the canonical results directory"
    )
    parser.add_argument(
        "--publish", action="store_true", help="replace specs/xbox_v1.json after validation"
    )
    args = parser.parse_args()

    catalog = json.loads(CATALOG_PATH.read_text())
    generated = make_spec(catalog)
    if args.command == "generate":
        if SPEC_PATH.exists():
            raise SystemExit(
                "Refusing to overwrite existing specification; use sync-spec --publish."
            )
        _atomic_json(SPEC_PATH, generated)
        return

    current = json.loads(SPEC_PATH.read_text())
    if args.command == "sync-spec":
        synchronized, report = validated_synchronize_spec(current, catalog)
        in_sync = current == synchronized
        if args.publish:
            _atomic_json(SPEC_PATH, synchronized)
            in_sync = True
        print(json.dumps({"schema_version": SCHEMA_VERSION, "in_sync": in_sync}, indent=2))
        if not in_sync:
            raise SystemExit(2)
        return

    report = audit(current, catalog)
    if args.output is not None:
        output = args.output.resolve()
        _atomic_json(output, report)
    print(json.dumps({
        "schema_valid": report["schema_valid"],
        "unresolved_count": len(report["unresolved_fields"]),
        "dynamics_ready": report["dynamics_ready"],
        "artifact_hash_status": report["artifact_hash_verification"]["status"],
    }, indent=2))
    if report["schema_errors"] or args.command == "require-dynamics":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
