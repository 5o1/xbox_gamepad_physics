#!/usr/bin/env python3
"""Load the Xbox backend through a real pinned RoboTwin Base_Task lifecycle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: Path):
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def articulation_pose(articulation):
    for name in ("get_root_pose", "get_pose"):
        getter = getattr(articulation, name, None)
        if callable(getter):
            return getter()
    raise RuntimeError("loaded articulation exposes no root-pose getter")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robotwin-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--pose",
        nargs=7,
        type=float,
        metavar=("X", "Y", "Z", "QW", "QX", "QY", "QZ"),
        required=True,
    )
    args = parser.parse_args()

    robotwin = args.robotwin_root.resolve(strict=True)
    sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(robotwin)]
    os.chdir(robotwin)

    from examples.robotwin_gamepad_asset_probe import robotwin_gamepad_asset_probe
    from xbox_gamepad_physics.state import GamepadState

    config_root = robotwin / "env_cfg" / "task_config"
    config = load_yaml(config_root / "demo_clean.yml")
    embodiment_index = load_yaml(config_root / "_embodiment_config.yml")
    robot_file = embodiment_index["aloha-agilex"]["file_path"]
    robot_directory = robotwin / robot_file
    embodiment_config = load_yaml(robot_directory / "config.yml")
    config.update(
        {
            "task_name": "robotwin_gamepad_asset_probe",
            "now_ep_num": 0,
            "seed": 0,
            "save_data": False,
            "eval_mode": False,
            "need_plan": False,
            "render_freq": 0,
            "left_robot_file": robot_file,
            "right_robot_file": robot_file,
            "left_embodiment_config": embodiment_config,
            "right_embodiment_config": embodiment_config,
            "dual_arm_embodied": True,
            "embodiment_name": "aloha-agilex",
        }
    )

    task = robotwin_gamepad_asset_probe()
    task.setup_demo(gamepad_pose=args.pose, gamepad_fixed_root=True, **config)
    first_scene = task.scene
    first_handle = task.gamepad
    neutral = task.gamepad_observation()
    command = GamepadState.xbox_one_s(
        {"left_x": 0.3, "left_y": -0.4, "right_trigger": 0.7, "south": 1.0}
    )
    task.gamepad.set_gamepad_state(command)
    observed = task.gamepad_observation()
    for _ in range(10):
        task.scene.step()

    root_pose = articulation_pose(task.gamepad.articulation)
    articulation_getter = getattr(task.scene, "get_all_articulations", None)
    if not callable(articulation_getter):
        raise RuntimeError("RoboTwin scene exposes no get_all_articulations()")
    articulations = list(articulation_getter())
    robot_articulations = {
        id(articulation): articulation
        for articulation in (task.robot.left_entity, task.robot.right_entity)
    }
    expected_articulations = [task.gamepad.articulation, *robot_articulations.values()]
    if any(articulation not in articulations for articulation in expected_articulations):
        raise RuntimeError("gamepad and robot articulations do not coexist in the scene")

    task.close_env()
    config["now_ep_num"] = 1
    task.setup_demo(gamepad_pose=args.pose, gamepad_fixed_root=True, **config)
    reset_state = task.gamepad_observation()
    reset_recreated_scene = task.scene is not first_scene
    reset_recreated_handle = task.gamepad is not first_handle
    reset_neutral = all(abs(value) <= 1e-12 for value in reset_state.values)

    result = {
        "robotwin_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=robotwin, text=True
        ).strip(),
        "consumer": "Base_Task.load_actors",
        "profile": "full_controls",
        "joint_count": len(task.gamepad.joint_names),
        "available_channel_count": sum(neutral.available_mask),
        "scene_articulation_count": len(articulations),
        "robot_articulation_count": len(robot_articulations),
        "roundtrip": {
            name: observed.channel(name)
            for name in ("left_x", "left_y", "right_trigger", "south")
        },
        "pose_owned_by_caller": list(args.pose),
        "observed_root_pose": {
            "position": [float(value) for value in root_pose.p],
            "quaternion_wxyz": [float(value) for value in root_pose.q],
        },
        "episode_rebuild": {
            "scene_recreated": reset_recreated_scene,
            "gamepad_handle_recreated": reset_recreated_handle,
            "gamepad_state_neutral": reset_neutral,
        },
    }
    if result["joint_count"] != 20 or result["available_channel_count"] != 21:
        raise RuntimeError(f"unexpected backend coverage: {result}")
    for name, expected in {
        "left_x": 0.3,
        "left_y": -0.4,
        "right_trigger": 0.7,
        "south": 1.0,
    }.items():
        if abs(result["roundtrip"][name] - expected) > 1e-6:
            raise RuntimeError(f"state roundtrip failed for {name}: {result}")
    if any(
        abs(result["observed_root_pose"]["position"][index] - args.pose[index]) > 1e-6
        for index in range(3)
    ):
        raise RuntimeError(f"caller pose was not applied to the root: {result}")
    if not all(result["episode_rebuild"].values()):
        raise RuntimeError(f"episode rebuild did not reset ownership/state: {result}")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
