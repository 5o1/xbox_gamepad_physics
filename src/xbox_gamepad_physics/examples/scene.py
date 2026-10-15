"""Shared SAPIEN scene and verified RoboTwin RT rendering setup."""

import math
import os
from pathlib import Path
import sys


from xbox_gamepad_physics.robotwin.scene import require_sapien
from xbox_gamepad_physics.robotwin import (
    apply_review_rendering,
    create_scene as _create_scene,
)


def create_render_scene(cfg: dict, *, shader="rt", samples_per_pixel=4, denoiser="oidn"):
    """Compatibility wrapper retaining the historical, global review defaults.

    New integrations should import create_scene/apply_review_rendering from
    xbox_gamepad_physics.robotwin. Review rendering changes all scene cameras.
    """
    if cfg.get("robotwin_root"):
        robotwin = Path(cfg["robotwin_root"]).expanduser().resolve(strict=True)
        sys.path[:0] = [str(robotwin)]
        os.chdir(robotwin)
    apply_review_rendering(shader=shader, samples_per_pixel=samples_per_pixel, denoiser=denoiser)
    return _create_scene(timestep=cfg["timestep"])


def create_scene(cfg: dict):
    """Compatibility wrapper for exported example configurations."""
    scene = (create_render_scene(cfg) if cfg["render"] else
             _create_scene(timestep=cfg["timestep"], render=False))
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
