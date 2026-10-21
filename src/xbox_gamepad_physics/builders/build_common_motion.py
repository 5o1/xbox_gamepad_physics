"""Build the simulator-independent Xbox One S motion contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .build_kinematics import build as build_kinematics


from .paths import DATA_ROOT, ROOT
from xbox_gamepad_physics.state import W3C_STANDARD_TO_CANONICAL  # noqa: E402

SOURCE = DATA_ROOT / "references" / "full_controls.json"
DEFAULT_OUTPUT = (
    ROOT
    / "build"
    / "standalone"
    / "common"
    / "xbox_one_s"
    / "motion"
    / "full_controls.json"
)
def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def build(output: Path = DEFAULT_OUTPUT, *, kinematics: Path | None = None,
          source: Path = SOURCE) -> dict:
    source = _json(source)
    profile = _json(kinematics) if kinematics is not None else build_kinematics()[1]
    neutral = float(source["signal_policy"]["device_neutral_epsilon"])
    stick_neutral = float(source["signal_policy"]["stick_neutral_epsilon"])

    profile_joints = {joint["id"]: joint for joint in profile["joints"]}
    joint_order = [
        joint_name
        for node in profile["nodes"]
        if node["control"] != "shell"
        for joint_name in node["joint_ids"]
    ]
    topology = {}
    for node in profile["nodes"]:
        control = node["control"]
        if control == "shell":
            continue
        parent = "controller_body"
        for index, joint_name in enumerate(node["joint_ids"]):
            child = control if index == len(node["joint_ids"]) - 1 else f"{joint_name}_frame"
            topology[joint_name] = {
                "parent": parent,
                "child": child,
                "origin": profile_joints[joint_name]["pivot_source_m"] if index == 0 else [0, 0, 0],
            }
            parent = child

    joints = []
    axes = []
    scalars = []
    splits = []
    events = []
    for name in joint_order:
        joint = profile_joints[name]
        joints.append(
            {
                "name": name,
                "type": joint["type"],
                **topology[name],
                "axis": joint["axis_source"],
                "lower": joint["limits"][0],
                "upper": joint["limits"][1],
                "unit": joint["unit"],
                "parameter_ref": joint["parameter_ref"],
            }
        )
        driver = joint["driver"]
        if driver["kind"] == "linear_channel":
            channel = W3C_STANDARD_TO_CANONICAL[int(driver["channel"])]
            binding = {"channel": channel, "joint": name}
            if channel in {"left_x", "left_y", "right_x", "right_y"}:
                axes.append(binding)
            else:
                binding["neutral_epsilon"] = neutral
                scalars.append(binding)
        elif driver["kind"] == "difference_channels":
            splits.append(
                {
                    "negative_channel": W3C_STANDARD_TO_CANONICAL[int(driver["negative_channel"])],
                    "positive_channel": W3C_STANDARD_TO_CANONICAL[int(driver["positive_channel"])],
                    "joint": name,
                }
            )
        elif driver["kind"] == "physical_event":
            events.append({"event": driver["event"], "joint": name})

    # The owner-requested circular mechanical boundary is expressed in shaft
    # direction, independently of the existing approximate signal envelopes.
    mechanical_limits = []
    for side in ("left", "right"):
        x_name, y_name = f"{side}_stick_x", f"{side}_stick_y"
        envelope = next(item for item in profile["constraints"]
                        if item["id"] == f"{side}_stick_radial_envelope")
        mechanical_limits.append({
            "id": f"{side}_stick_circular_limit",
            "type": "shaft_tilt_limit",
            "joint_ids": [x_name, y_name],
            "reference_link": topology[x_name]["parent"],
            "moving_link": topology[y_name]["child"],
            "pivot_in_reference_m": topology[x_name]["origin"],
            "pivot_in_moving_m": [0.0, 0.0, 0.0],
            "reference_axis": [0.0, 0.0, 1.0],
            "moving_axis": [0.0, 0.0, 1.0],
            "max_angle_rad": envelope["radius"],
            "enforcement": "hard",
            "required_stages": ["initialization", "state_write", "each_physics_substep"],
            "boundary_velocity": "no_outward_velocity",
            "on_unsupported": "error",
            "signal_projection_is_enforcement": False,
            "parameter_ref": envelope["parameter_ref"],
            "coordinate_space": "relative_shaft_direction",
            "boundary": "acos(dot(reference_axis, moving_axis_in_reference)) <= max_angle_rad",
            "model_status": "owner_requested_circular_simulation_gate",
            "basis": "Owner request 2026-10-19; retain the existing cardinal tilt limit. This is not hardware identification.",
            "independent_of": [f"{side}_stick_click"],
        })

    contract = {
        "schema_version": 1,
        "asset_id": "xbox_one_s",
        "profile": source["profile"],
        "scope": "simulator-independent joint ranges and gamepad signal constraints",
        "source_records": [
            "references/stick_envelope.json",
            "references/xbox_one_s_artist_animation_summary.json",
            "references/full_controls.json",
        ],
        "joints": joints,
        "bindings": {
            "axes": axes,
            "scalars": scalars,
            "splits": splits,
            "radial_groups": [
                {
                    "channels": ["left_x", "left_y"],
                    "radius": 1.0,
                    "neutral_epsilon": stick_neutral,
                },
                {
                    "channels": ["right_x", "right_y"],
                    "radius": 1.0,
                    "neutral_epsilon": stick_neutral,
                },
            ],
            "radial_source_groups": [
                {
                    "joints": ["dpad_horizontal", "dpad_vertical"],
                    "radius": 1.0,
                    "neutral_epsilon": neutral,
                }
            ],
            "physical_events": events,
        },
        "signal_policy": source["signal_policy"],
        "joint_space_constraints": [*profile["constraints"], *mechanical_limits],
    }
    encoded = json.dumps(contract, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, output)
    return contract


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    contract = build(args.output.resolve())
    print(json.dumps({"output": str(args.output.resolve()), "joints": len(contract["joints"])}))


if __name__ == "__main__":
    main()
