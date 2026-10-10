"""Shared SAPIEN scene and verified RoboTwin RT rendering setup."""

import math
import os
from pathlib import Path
import sys


def create_scene(cfg: dict):
    if cfg["render"]:
        robotwin = Path(cfg["robotwin_root"]).expanduser().resolve(strict=True)
        sys.path[:0] = [str(robotwin)]
        os.chdir(robotwin)

        import sapien
        from sapien.render import set_global_config

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
        scene.set_timestep(cfg["timestep"])
        scene.set_ambient_light([0.5, 0.5, 0.5])
        scene.add_directional_light([0, 0.5, -1], [0.5, 0.5, 0.5], shadow=True)
        scene.add_point_light([1, 0, 1.8], [1, 1, 1], shadow=True)
        scene.add_point_light([-1, 0, 1.8], [1, 1, 1], shadow=True)
    else:
        import sapien

        scene = sapien.Scene()
        scene.set_timestep(cfg["timestep"])
    if cfg["ground"]:
        scene.add_ground(0)
    return scene


def look_at(position, target):
    import numpy as np
    import sapien
    from transforms3d.quaternions import mat2quat

    forward = np.asarray(target) - np.asarray(position)
    forward /= np.linalg.norm(forward)
    left = np.cross([0, 0, 1], forward)
    left /= np.linalg.norm(left)
    up = np.cross(forward, left)
    return sapien.Pose(p=position, q=mat2quat(np.column_stack([forward, left, up])))


def create_camera(scene, cfg: dict):
    camera = scene.add_camera(
        "review", cfg["width"], cfg["height"], math.radians(cfg["fovy_degrees"]),
        cfg["near"], cfg["far"],
    )
    camera.entity.set_pose(look_at(cfg["position"], cfg["target"]))
    return camera


def take_picture(scene, camera, output: Path) -> None:
    import cv2
    import numpy as np

    scene.update_render()
    camera.take_picture()
    rgba = camera.get_picture("Color")
    bgr = np.ascontiguousarray(
        np.rint(np.clip(rgba[..., :3], 0, 1) * 255).astype(np.uint8)[..., ::-1]
    )
    if not cv2.imwrite(str(output), bgr):
        raise OSError(f"could not write frame: {output}")
