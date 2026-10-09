"""Build the simulator-independent Xbox One S motion contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from build_kinematics import build as build_kinematics


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from xbox_gamepad_physics.state import W3C_STANDARD_TO_CANONICAL  # noqa: E402

SOURCE = ROOT / "references" / "full_controls.json"
DEFAULT_OUTPUT = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
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


def build(output: Path = DEFAULT_OUTPUT) -> dict:
    source = _json(SOURCE)
    _, profile, _ = build_kinematics()
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
        "joint_space_constraints": profile["constraints"],
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
