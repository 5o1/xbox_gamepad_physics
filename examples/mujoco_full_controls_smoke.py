"""Run a non-visual MuJoCo smoke test for the full Xbox controls."""

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

    import mujoco
    import numpy as np

    from xbox_gamepad_physics import load_motion_contract
    from xbox_gamepad_physics.mujoco import load_scene
    from xbox_gamepad_physics.state import GamepadState

    loaded = load_scene(profile="full_controls", scene="fixed")
    gamepad = loaded.gamepad
    state_mapping = load_motion_contract("full_controls").state_mapping
    neutral = gamepad.gamepad_state()

    endpoint_checks = {}
    for group in ("axes", "scalars"):
        for mapping in state_mapping[group]:
            gamepad.joint_data(mapping["joint"]).qpos[0] = mapping["upper"]
            mujoco.mj_forward(loaded.model, loaded.data)
            endpoint_checks[mapping["channel"]] = gamepad.gamepad_state().channel(
                mapping["channel"]
            )
            gamepad.joint_data(mapping["joint"]).qpos[0] = 0.0
    for mapping in state_mapping["splits"]:
        for side, position in (
            ("negative_channel", mapping["lower"]),
            ("positive_channel", mapping["upper"]),
        ):
            gamepad.joint_data(mapping["joint"]).qpos[0] = position
            mujoco.mj_forward(loaded.model, loaded.data)
            endpoint_checks[mapping[side]] = gamepad.gamepad_state().channel(
                mapping[side]
            )
            gamepad.joint_data(mapping["joint"]).qpos[0] = 0.0

    event = state_mapping["physical_events"][0]
    gamepad.joint_data(event["joint"]).qpos[0] = event["upper"]
    mujoco.mj_forward(loaded.model, loaded.data)
    physical_events = gamepad.physical_events()
    gamepad.joint_data(event["joint"]).qpos[0] = 0.0

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
    mujoco.mj_forward(loaded.model, loaded.data)
    observed_command = gamepad.gamepad_state()
    roundtrip_error = max(
        abs(observed_command.channel(name) - value)
        for name, value in command_values.items()
    )
    gamepad.set_physical_events({"pair_bind_connect": 0.45})
    mujoco.mj_forward(loaded.model, loaded.data)
    pair_roundtrip_error = abs(
        gamepad.physical_events()["pair_bind_connect"] - 0.45
    )

    initial = {}
    for name in gamepad.joint_names:
        model_joint = gamepad.joint(name)
        upper = float(model_joint.range[1])
        value = 0.25 * upper
        gamepad.joint_data(name).qpos[0] = value
        initial[name] = value
    loaded.data.qvel[:] = 0.0
    mujoco.mj_forward(loaded.model, loaded.data)
    initial_contacts = []
    for index in range(loaded.data.ncon):
        contact = loaded.data.contact[index]
        geom1 = loaded.model.geom(int(contact.geom1))
        geom2 = loaded.model.geom(int(contact.geom2))
        body1 = loaded.model.body(int(loaded.model.geom_bodyid[int(contact.geom1)]))
        body2 = loaded.model.body(int(loaded.model.geom_bodyid[int(contact.geom2)]))
        initial_contacts.append(
            {
                "body1": body1.name,
                "geom1": geom1.name,
                "body2": body2.name,
                "geom2": geom2.name,
                "distance": float(contact.dist),
            }
        )
    for _ in range(args.steps):
        mujoco.mj_step(loaded.model, loaded.data)
    final = gamepad.joint_positions()

    result = {
        "mujoco": mujoco.__version__,
        "profile": "full_controls",
        "joint_count": len(gamepad.joint_names),
        "sensor_count": len(gamepad.sensor_names),
        "available_game_channels": sum(neutral.available_mask),
        "endpoint_checks": endpoint_checks,
        "physical_events": physical_events,
        "command_roundtrip_max_error": roundtrip_error,
        "pair_roundtrip_error": pair_roundtrip_error,
        "return_initial": initial,
        "return_final": final,
        "initial_contacts": initial_contacts,
        "return_initial_l1": sum(abs(value) for value in initial.values()),
        "return_final_l1": sum(abs(value) for value in final.values()),
        "finite": all(np.isfinite(value) for value in final.values()),
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
