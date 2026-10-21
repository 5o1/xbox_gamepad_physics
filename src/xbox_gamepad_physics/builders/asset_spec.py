"""Generate the unresolved Xbox evidence specification.

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


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "sync-spec"])
    parser.add_argument("--publish", action="store_true", help="write the generated specification")
    args = parser.parse_args()
    catalog = json.loads(CATALOG_PATH.read_text())
    generated = make_spec(catalog)
    if args.command == "generate" or args.publish:
        if args.command == "generate" and SPEC_PATH.exists():
            raise SystemExit("Specification already exists; use sync-spec --publish to replace it.")
        _atomic_json(SPEC_PATH, generated)
    else:
        print(json.dumps(generated, indent=2))


if __name__ == "__main__":
    main()
