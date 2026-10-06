"""Evidence-bound Xbox physical specification; no implicit numeric defaults.

Reference component values are deliberately separate from target parameters.
This is an incomplete asset specification, not a simulator-ready URDF.
"""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "geometry_scale",
    "mass",
    "center_of_mass",
    "inertia",
    "collision_geometry",
    "contact_friction",
    "contact_restitution",
)
MOVING = (
    "joint_type",
    "joint_origin",
    "joint_axis",
    "joint_limits",
    "restoring_curve",
    "damping",
    "joint_friction",
    "input_mapping",
)
UNITS = dict(
    geometry_scale="m/native_unit",
    mass="kg",
    center_of_mass="m",
    inertia="kg*m^2",
    contact_friction="1",
    contact_restitution="1",
    joint_origin="m,rad",
    joint_axis="1",
)
CONTROLS = (
    "shell",
    "a",
    "b",
    "x",
    "y",
    "left_stick",
    "right_stick",
    "dpad",
    "left_shoulder",
    "right_shoulder",
    "left_trigger",
    "right_trigger",
    "view",
    "menu",
    "guide",
)


def unknown(name):
    return {
        "value": None,
        "unit": UNITS.get(name),
        "status": "unknown",
        "evidence": [],
        "harness": "audit_spec",
        "reason": f"No verified target-hardware evidence for {name}; no simulator default permitted.",
    }


def make_spec(catalog):
    return {
        "schema_version": 1,
        "catalog_sha256": hashlib.sha256(
            json.dumps(catalog, sort_keys=True).encode()
        ).hexdigest(),
        "hardware_revision": {
            "value": "1708",
            "unit": None,
            "status": "user_confirmed",
            "evidence": ["user_target_1708"],
            "harness": "audit_spec",
            "applicability": "Owner identifies the Xbox One 1708 as the target; no physical measurements inferred.",
        },
        "status": "incomplete_not_for_dynamics_or_RL",
        "component_inventory_basis": {
            "evidence": ["user_target_1708", "ifixit_1708_buttons"],
            "scope": "1708 target; visual source remains unverified for this revision. No Share control on target.",
            "harness": "export_blend_inventory",
        },
        "parts": {
            name: {
                key: unknown(key)
                for key in REQUIRED + (() if name == "shell" else MOVING)
            }
            for name in CONTROLS
        },
        "reference_candidates": {
            "left_stick": [
                "stick_direction_limit",
                "stick_operating_torque",
                "stick_click_force",
                "stick_click_travel",
                "stick_return_precision",
            ],
            "right_stick": [
                "stick_direction_limit",
                "stick_operating_torque",
                "stick_click_force",
                "stick_click_travel",
                "stick_return_precision",
            ],
            **{name: ["front_force", "front_travel"] for name in ("a", "b", "x", "y")},
            **{
                name: ["shoulder_force", "shoulder_travel"]
                for name in ("left_shoulder", "right_shoulder")
            },
        },
        "reference_policy": "Candidates are NOT assigned to target parameters. Adoption requires explicit applicability rationale, unit-correct derivation and a test.",
        "dpad_policy": "Visual direction labels do not establish four independent mechanical buttons; topology unresolved.",
        "stick_policy": "Must account for two-axis tilt and click; axes, coupling and limits unresolved. Never infer pivot from Blender origin.",
        "trigger_policy": "Do not replace analog triggers with Alpakka digital trigger switches.",
    }


def audit(spec, catalog):
    errors, missing = [], []
    revision = spec.get("hardware_revision")
    if not isinstance(revision, dict):
        errors.append("hardware_revision: missing field")
    elif revision.get("value") is None:
        missing.append("hardware_revision")
        if revision.get("status") != "unknown" or not revision.get("reason"):
            errors.append("hardware_revision: undocumented unknown")
    elif (
        revision.get("value") != "1708"
        or revision.get("status") != "user_confirmed"
        or revision.get("evidence") != ["user_target_1708"]
        or "user_target_1708" not in catalog["sources"]
        or not revision.get("applicability")
        or not revision.get("harness")
    ):
        errors.append("hardware_revision: does not match documented target confirmation")
    expected = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
    if spec.get("catalog_sha256") != expected:
        errors.append("source catalog hash mismatch")
    if set(spec.get("parts", {})) != set(CONTROLS):
        errors.append("component coverage changed")
    for name in CONTROLS:
        fields = spec.get("parts", {}).get(name, {})
        for key in REQUIRED + (() if name == "shell" else MOVING):
            path = f"{name}.{key}"
            item = fields.get(key)
            if not isinstance(item, dict):
                errors.append(f"{path}: field missing")
                continue
            if item.get("value") is None:
                missing.append(path)
                if item.get("status") != "unknown" or not item.get("reason"):
                    errors.append(f"{path}: undocumented unknown")
            else:
                if item.get("status") not in (
                    "measured",
                    "derived",
                    "reference_adopted",
                ):
                    errors.append(f"{path}: unsupported evidence status")
                refs = item.get("evidence", [])
                if not refs or any(r not in catalog["sources"] for r in refs):
                    errors.append(f"{path}: missing/invalid evidence")
                if not item.get("harness") or not item.get("applicability"):
                    errors.append(f"{path}: missing harness or applicability")
                if key in UNITS and item.get("unit") != UNITS[key]:
                    errors.append(f"{path}: wrong units")
    # Human review is mandatory even if all fields are eventually supplied.
    return {
        "schema_errors": errors,
        "unresolved_fields": missing,
        "schema_valid": not errors,
        "dynamics_ready": False,
        "readiness_reason": "No simulator/contact validation has been performed; schema completeness alone never enables dynamics.",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["generate", "audit", "require-dynamics"])
    args = p.parse_args()
    catalog = json.loads((ROOT / "sources/catalog.json").read_text())
    path = ROOT / "specs/xbox_v1.json"
    if args.command == "generate":
        if path.exists():
            raise SystemExit("Refusing to overwrite existing specification.")
        path.write_text(
            json.dumps(make_spec(catalog), ensure_ascii=False, indent=2) + "\n"
        )
    spec = json.loads(path.read_text())
    report = audit(spec, catalog)
    (ROOT / "results/spec_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "schema_valid": report["schema_valid"],
                "unresolved_count": len(report["unresolved_fields"]),
                "dynamics_ready": report["dynamics_ready"],
            },
            indent=2,
        )
    )
    if report["schema_errors"] or args.command == "require-dynamics":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
