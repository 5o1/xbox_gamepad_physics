"""Render the Xbox One S visual asset with MuJoCo's Filament backend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=("reference", "table"), default="reference")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--graphics", default="opengl_headless")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    import mujoco
    import mujoco._render_filament as mjrf
    from mujoco.experimental.studio import window
    from mujoco.rendering.filament import renderer as filament_renderer

    from xbox_gamepad_physics.mujoco import load_visual_scene

    loaded = load_visual_scene(scene=args.scene, renderer="filament")
    api = (
        mjrf.GraphicsApi.GRAPHICS_API_VULKAN
        if args.graphics.startswith("vulkan")
        else mjrf.GraphicsApi.GRAPHICS_API_OPENGL
    )
    resource_window = window.Window(
        "Xbox One S Filament resources", 32, 32, args.graphics
    )
    context = mjrf.Context(mjrf.ContextConfig(graphics_api=api))
    renderer = filament_renderer.Renderer(context)
    objects = mjrf.ModelObjects(context, loaded.model)
    scene = renderer.scene("xbox")
    scene.configure_from_model(loaded.model)
    lights = mjrf.ModelLights(scene, objects)
    renderables = mjrf.ModelRenderables(scene, objects)
    lights.update(loaded.data)
    renderables.update(loaded.data)

    pixels = np.empty((900, 1600, 3), dtype=np.uint8)
    renderer.target("rgb", pixels)
    renderer.view("main", scene="xbox", target="rgb")
    camera_names = (
        ("reference_camera",)
        if args.scene == "reference"
        else ("head_camera", "review_oblique")
    )
    captures = []
    for camera_name in camera_names:
        camera = mujoco.MjvCamera()
        camera.type = int(mujoco.mjtCamera.mjCAMERA_FIXED)
        camera.fixedcamid = loaded.model.camera(camera_name).id
        renderer.update_camera(
            "main", mujoco.mjv_camera2GLCamera(loaded.model, loaded.data, camera)
        )
        started = time.perf_counter()
        renderer.render()
        elapsed = time.perf_counter() - started
        path = args.output / f"{camera_name}.png"
        Image.fromarray(pixels).save(path)
        captures.append({"camera": camera_name, "seconds": elapsed, "file": path.name})

    report = {
        "python": sys.version.split()[0],
        "mujoco": mujoco.__version__,
        "renderer": "filament",
        "graphics": args.graphics,
        "scene": args.scene,
        "physics_ready": loaded.physics_ready,
        "captures": captures,
    }
    (args.output / "result.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report))
    del resource_window


if __name__ == "__main__":
    main()
