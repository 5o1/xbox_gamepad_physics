#!/usr/bin/env python3
"""Minimal RoboTwin simulation experiment template.

Keep the renderer and asset-loading blocks unchanged. Put each experiment's
actors and per-step stimulus only in the two marked sections below.
"""

import argparse
import json
import math
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--robotwin-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--free-root", action="store_true")
    parser.add_argument("--ground", action="store_true")
    args = parser.parse_args()

    robotwin = args.robotwin_root.resolve(strict=True)
    package = args.package_root.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(package), str(robotwin)]
    os.chdir(robotwin)

    import cv2
    import numpy as np
    import sapien
    from sapien.render import set_global_config
    from transforms3d.quaternions import mat2quat

    from xbox_gamepad_physics.robotwin import load_into_scene

    # Verified RoboTwin RT setup. Do not replace this with bare sapien.Scene().
    engine = sapien.Engine()
    set_global_config(max_num_materials=50000, max_num_textures=50000)
    renderer = sapien.SapienRenderer()
    engine.set_renderer(renderer)
    sapien.render.set_camera_shader_dir("rt")
    sapien.render.set_ray_tracing_samples_per_pixel(4)
    sapien.render.set_ray_tracing_path_depth(8)
    sapien.render.set_ray_tracing_denoiser("oidn")
    scene = engine.create_scene(sapien.SceneConfig())
    scene.set_timestep(1 / 240)
    scene.set_ambient_light([0.5, 0.5, 0.5])
    scene.add_directional_light([0, 0.5, -1], [0.5, 0.5, 0.5], shadow=True)
    scene.add_point_light([1, 0, 1.8], [1, 1, 1], shadow=True)
    scene.add_point_light([-1, 0, 1.8], [1, 1, 1], shadow=True)
    if args.ground:
        scene.add_ground(0)

    gamepad = load_into_scene(
        scene=scene,
        pose=sapien.Pose(),
        fixed_root=not args.free_root,
        profile="full_controls",
    )

    # === EXPERIMENT SETUP: add probes, table, robot, or other actors here. ===

    def look_at(position, target):
        forward = np.asarray(target) - np.asarray(position)
        forward /= np.linalg.norm(forward)
        left = np.cross([0, 0, 1], forward)
        left /= np.linalg.norm(left)
        up = np.cross(forward, left)
        return sapien.Pose(p=position, q=mat2quat(np.column_stack([forward, left, up])))

    camera = scene.add_camera("review", 1280, 720, math.radians(40), 0.001, 10)
    camera.entity.set_pose(look_at([0, -0.30, 0.17], [0, 0, 0]))

    for step in range(240):
        simulation_time = step / 240

        # === EXPERIMENT STEP: apply the physical stimulus here. ===

        scene.step()

    # Read signals only from simulated articulation state.
    state = gamepad.gamepad_state()
    scene.update_render()
    camera.take_picture()
    rgba = camera.get_picture("Color")
    bgr = np.ascontiguousarray(
        np.rint(np.clip(rgba[..., :3], 0, 1) * 255).astype(np.uint8)[..., ::-1]
    )
    cv2.imwrite(str(output / "frame.png"), bgr)
    (output / "state.json").write_text(
        json.dumps(
            {
                "layout_id": state.layout_id,
                "values": list(state.values),
                "available_mask": list(state.available_mask),
                "task_mask": list(state.task_mask),
                "device_id": state.device_id,
                "qpos": gamepad.joint_positions(),
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
