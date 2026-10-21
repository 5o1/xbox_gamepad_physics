"""Export a small MuBlE-compatible pose trace through the public MuJoCo API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xbox_gamepad_physics.muble import PoseCommand, export_pose_trace
from xbox_gamepad_physics.mujoco import load_scene
from xbox_gamepad_physics.state import GamepadState


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    loaded = load_scene(profile="full_controls", scene="fixed")
    trace = export_pose_trace(
        loaded,
        (
            PoseCommand("neutral", GamepadState.xbox_one_s({})),
            PoseCommand("a_pressed", GamepadState.xbox_one_s({"south": 1.0})),
            PoseCommand(
                "left_stick_x_positive",
                GamepadState.xbox_one_s({"left_x": 1.0}),
            ),
        ),
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "frames": len(trace["frames"])}))


if __name__ == "__main__":
    main()
