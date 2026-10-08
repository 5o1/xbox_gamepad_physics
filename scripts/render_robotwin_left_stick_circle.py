"""Render the canonical circle trace on the RoboTwin/SAPIEN Xbox asset."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robotwin-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-frames", type=int)
    args = parser.parse_args()

    package_root = args.package_root.resolve()
    robotwin_root = args.robotwin_root.resolve()
    sys.path.insert(0, str(package_root))
    sys.path.insert(0, str(robotwin_root))
    os.chdir(robotwin_root)

    import cv2
    import numpy as np
    import sapien
    from transforms3d.quaternions import mat2quat

    from envs._base_task import create_box, create_table
    from xbox_gamepad_physics.robotwin import load_into_scene

    trace = json.loads(args.trace.resolve().read_text(encoding="utf-8"))
    if trace.get("demo") != "left_stick_unit_circle":
        raise ValueError("trace is not the left-stick unit-circle demonstration")

    def look_at(position, target):
        forward = np.asarray(target) - np.asarray(position)
        forward /= np.linalg.norm(forward)
        left = np.cross([0, 0, 1], forward)
        left /= np.linalg.norm(left)
        up = np.cross(forward, left)
        return sapien.Pose(
            p=position,
            q=mat2quat(np.column_stack([forward, left, up])),
        )

    scene = sapien.Scene()
    scene.set_timestep(1.0 / 250.0)
    scene.add_ground(0.0)
    scene.default_physical_material = scene.create_physical_material(0.5, 0.5, 0.0)
    scene.set_ambient_light([0.38, 0.38, 0.38])
    scene.add_directional_light([0.4, 0.5, -1], [1.1, 1.1, 1.1], shadow=True)
    scene.add_directional_light([-0.6, -0.2, -1], [0.45, 0.47, 0.5], shadow=False)
    create_box(
        scene,
        sapien.Pose(p=[0, 1, 1.5]),
        half_size=[3, 0.6, 1.5],
        color=(0.82, 0.84, 0.87),
        name="wall",
        is_static=True,
    )
    create_table(
        scene,
        sapien.Pose(p=[0, 0, 0.74]),
        length=1.2,
        width=0.7,
        height=0.74,
        thickness=0.05,
        color=(0.24, 0.28, 0.32),
        name="table",
        is_static=True,
    )
    gamepad = load_into_scene(
        scene,
        pose=sapien.Pose(p=[0, 0, 0.8]),
        fixed_root=True,
        profile="left_stick_estimated_v0",
    )
    camera = scene.add_camera(
        "left_stick_circle_camera",
        1280,
        720,
        math.radians(37),
        0.001,
        10,
    )
    camera.entity.set_pose(
        look_at(
            np.array([0.12, -0.20, 0.96]),
            np.array([0.035, 0.020, 0.77]),
        )
    )

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    articulation = gamepad.articulation
    frames = trace["frames"]
    if args.max_frames is not None:
        if args.max_frames <= 0:
            raise ValueError("max_frames must be positive")
        frames = frames[: args.max_frames]
    for frame_index, frame in enumerate(frames):
        telemetry = frame["telemetry"]
        gamepad.set_joint_positions(
            {
                "left_stick_x": telemetry["left_stick_x_rad"],
                "left_stick_y": telemetry["left_stick_y_rad"],
            }
        )
        articulation.set_qvel(np.zeros(2))
        scene.update_render()
        camera.take_picture()
        rgba = camera.get_picture("Color")
        bgr = np.ascontiguousarray(
            np.rint(np.clip(rgba[..., :3], 0, 1) * 255)
            .astype(np.uint8)[..., ::-1]
        )
        cv2.putText(
            bgr,
            "RoboTwin / SAPIEN  |  Xbox One S physical asset",
            (28, 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (245, 245, 245),
            2,
            cv2.LINE_AA,
        )
        cv2.imwrite(str(output / f"frame_{frame_index:04d}.png"), bgr)

    print(
        json.dumps(
            {
                "output": str(output),
                "frames": len(frames),
                "fps": trace["fps"],
                "resolution": [1280, 720],
                "sapien": sapien.__version__,
                "renderer": "sapien_raster",
            }
        )
    )


if __name__ == "__main__":
    main()
