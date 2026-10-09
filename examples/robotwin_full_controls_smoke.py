"""Run a non-visual SAPIEN smoke test for the full Xbox control articulation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=500)
    args = parser.parse_args()

    import numpy as np
    import sapien

    from xbox_gamepad_physics import load_motion_contract
    from xbox_gamepad_physics.resources import load_json_resource, resource_path
    from xbox_gamepad_physics.robotwin import load_into_scene
    from xbox_gamepad_physics.state import GamepadState

    scene = sapien.Scene()
    scene.set_timestep(1.0 / 240.0)
    gamepad = load_into_scene(
        scene,
        pose=sapien.Pose(),
        fixed_root=True,
        profile="full_controls",
        attach_visual=False,
    )
    manifest = load_json_resource("robotwin", "full_controls")
    motion = load_motion_contract("full_controls")
    state_mapping = motion.state_mapping
    joint_limits = _joint_limits(resource_path(
        "robotwin", "full_controls", "mobility.urdf"
    ))

    neutral = gamepad.gamepad_state()
    endpoint_checks = {}
    for mapping_group in ("axes", "scalars"):
        for mapping in state_mapping[mapping_group]:
            gamepad.set_joint_positions({mapping["joint"]: mapping["upper"]})
            state = gamepad.gamepad_state()
            endpoint_checks[mapping["channel"]] = state.channel(mapping["channel"])
            gamepad.set_joint_positions({mapping["joint"]: 0.0})
    for mapping in state_mapping["splits"]:
        for side, position in (
            ("negative_channel", mapping["lower"]),
            ("positive_channel", mapping["upper"]),
        ):
            gamepad.set_joint_positions({mapping["joint"]: position})
            state = gamepad.gamepad_state()
            endpoint_checks[mapping[side]] = state.channel(mapping[side])
            gamepad.set_joint_positions({mapping["joint"]: 0.0})

    event = state_mapping["physical_events"][0]
    gamepad.set_joint_positions({event["joint"]: event["upper"]})
    physical_events = gamepad.physical_events()
    gamepad.set_joint_positions({event["joint"]: 0.0})

    command_values = {
        "left_x": 0.3, "left_y": -0.4, "right_x": -0.2, "right_y": 0.1,
        "left_trigger": 0.35, "right_trigger": 0.7,
        "south": 1.0, "east": 0.25, "west": 0.5, "north": 0.75,
        "back": 1.0, "guide": 0.2, "start": 0.6,
        "left_stick": 0.4, "right_stick": 0.8,
        "left_shoulder": 0.3, "right_shoulder": 0.9,
        "dpad_left": 0.4, "dpad_down": 0.6,
    }
    command = GamepadState.xbox_one_s(command_values)
    gamepad.set_gamepad_state(command)
    observed_command = gamepad.gamepad_state()
    roundtrip_error = max(
        abs(observed_command.channel(name) - value)
        for name, value in command_values.items()
    )
    gamepad.set_physical_events({"pair_bind_connect": 0.45})
    pair_roundtrip_error = abs(
        gamepad.physical_events()["pair_bind_connect"] - 0.45
    )

    initial = {}
    for item in manifest["joint_dynamics"]:
        joint_name = item["name"]
        joint_manifest = next(
            joint
            for joint in joint_limits
            if joint["name"] == joint_name
        )
        initial[joint_name] = 0.25 * joint_manifest["upper"]
    gamepad.set_joint_positions(initial)
    gamepad.articulation.set_qvel(np.zeros(len(gamepad.joint_names)))
    for _ in range(args.steps):
        scene.step()
    final = gamepad.joint_positions()

    result = {
        "sapien": sapien.__version__,
        "profile": "full_controls",
        "joint_count": len(gamepad.joint_names),
        "available_game_channels": sum(neutral.available_mask),
        "endpoint_checks": endpoint_checks,
        "physical_events": physical_events,
        "command_roundtrip_max_error": roundtrip_error,
        "pair_roundtrip_error": pair_roundtrip_error,
        "return_initial_l1": sum(abs(value) for value in initial.values()),
        "return_final_l1": sum(abs(value) for value in final.values()),
        "finite": all(np.isfinite(value) for value in final.values()),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


def _joint_limits(path: Path) -> list[dict]:
    import xml.etree.ElementTree as ET

    result = []
    for joint in ET.parse(path).getroot().findall("joint"):
        limit = joint.find("limit")
        result.append(
            {
                "name": joint.get("name"),
                "lower": float(limit.get("lower")),
                "upper": float(limit.get("upper")),
            }
        )
    return result


if __name__ == "__main__":
    main()
