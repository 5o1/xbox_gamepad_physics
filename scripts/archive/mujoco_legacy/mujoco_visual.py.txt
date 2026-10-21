"""Render or interactively inspect the MuJoCo visual-only table scene."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("/tmp/xgp-mujoco-visual")
    )
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("MUJOCO_GL", "glfw" if args.interactive else "egl")
    import mujoco

    from xbox_gamepad_physics.mujoco import load_visual_scene

    loaded = load_visual_scene(scene="table")
    renderer = mujoco.Renderer(loaded.model, height=900, width=1600)
    captures = []
    for name in ("head_camera", "review_oblique"):
        started = time.perf_counter()
        renderer.update_scene(loaded.data, camera=name)
        pixels = renderer.render()
        elapsed = time.perf_counter() - started
        Image.fromarray(pixels).save(args.output / f"{name}.png")
        captures.append({"view": name, "seconds": elapsed})

    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.lookat[:] = [0, 0, 0.8]
    camera.distance = 0.8
    camera.elevation = -38
    timings = []
    for azimuth in np.linspace(-35, 35, 30):
        camera.azimuth = float(azimuth)
        started = time.perf_counter()
        renderer.update_scene(loaded.data, camera=camera)
        renderer.render()
        timings.append(time.perf_counter() - started)

    report = {
        "mujoco_version": mujoco.__version__,
        "parts": len(loaded.manifest["parts"]),
        "physics_ready": loaded.physics_ready,
        "captures": captures,
        "orbit_frame_seconds": timings,
        "mean_orbit_fps": 1 / float(np.mean(timings)),
        "material_limitations": loaded.manifest["native_renderer_material"][
            "limitations"
        ],
    }
    (args.output / "result.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report), flush=True)
    renderer.close()

    if args.interactive:
        import mujoco.viewer

        with mujoco.viewer.launch_passive(loaded.model, loaded.data) as viewer:
            while viewer.is_running():
                viewer.sync()
                time.sleep(1 / 60)


if __name__ == "__main__":
    main()
