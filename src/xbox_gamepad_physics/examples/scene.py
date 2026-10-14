"""Shared SAPIEN scene and verified RoboTwin RT rendering setup."""

import math
import os
from pathlib import Path
import sys


def require_sapien():
    from xbox_gamepad_physics.errors import MissingBackendDependencyError
    try:
        import sapien
    except ModuleNotFoundError as error:
        if error.name != "sapien":
            raise
        raise MissingBackendDependencyError("This example requires SAPIEN 3.0.3; install the wheel with the [robotwin] extra.") from error
    return sapien


def create_render_scene(cfg: dict, *, shader="rt", samples_per_pixel=4, denoiser="oidn"):
    """RoboTwin's renderer and default lights, shared by all rendering processes.

    Defaults retain the repository's verified RT setup. Raster consumers select
    shader="default"; their lighting and material/texture limits stay identical.
    RoboTwin's import-time assets require its root as the working directory.
    """
    if shader not in ("rt", "default") or samples_per_pixel < 1:
        raise ValueError("expected rt/default shader and positive samples_per_pixel")
    # Keep all renderer configuration inside this public entry.
    # Optional platform root preserves checkout/teleop callers. Native example
    # scenes use SAPIEN directly and do not need a RoboTwin working directory.
    if cfg.get("robotwin_root"):
        robotwin = Path(cfg["robotwin_root"]).expanduser().resolve(strict=True)
        sys.path[:0] = [str(robotwin)]
        os.chdir(robotwin)

    sapien = require_sapien()
    from sapien.render import set_global_config

    # Verified RoboTwin RT setup. Do not replace this with bare sapien.Scene().
    engine = sapien.Engine()
    set_global_config(max_num_materials=50000, max_num_textures=50000)
    renderer = sapien.SapienRenderer()
    engine.set_renderer(renderer)
    sapien.render.set_camera_shader_dir(shader)
    sapien.render.set_ray_tracing_samples_per_pixel(samples_per_pixel)
    sapien.render.set_ray_tracing_path_depth(8)
    sapien.render.set_ray_tracing_denoiser(denoiser)
    scene = engine.create_scene(sapien.SceneConfig())
    scene.set_timestep(cfg["timestep"])
    scene.set_ambient_light([0.5, 0.5, 0.5])
    scene.add_directional_light([0, 0.5, -1], [0.5, 0.5, 0.5], shadow=True)
    scene.add_point_light([1, 0, 1.8], [1, 1, 1], shadow=True)
    scene.add_point_light([-1, 0, 1.8], [1, 1, 1], shadow=True)
    return scene


def create_scene(cfg: dict):
    if cfg["render"]:
        scene = create_render_scene(cfg)
    else:
        sapien = require_sapien()

        scene = sapien.Scene()
        scene.set_timestep(cfg["timestep"])
    if cfg["ground"]:
        scene.add_ground(0)
    return scene


def look_at(position, target, up_hint=(0, 0, 1)):
    import numpy as np
    import sapien
    from transforms3d.quaternions import mat2quat

    forward = np.asarray(target) - np.asarray(position)
    forward /= np.linalg.norm(forward)
    if abs(np.dot(forward, up_hint)) > .999999:
        up_hint = (0, 1, 0)
    left = np.cross(up_hint, forward)
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
    from PIL import Image
    import numpy as np

    scene.update_render()
    camera.take_picture()
    rgba = camera.get_picture("Color")
    rgb = np.rint(np.clip(rgba[..., :3], 0, 1) * 255).astype(np.uint8)
    Image.fromarray(rgb).save(output)
