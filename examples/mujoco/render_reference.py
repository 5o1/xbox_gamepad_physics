"""Render complete native geometry with the unchanged D2 camera plan using EGL."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def render(resource_root, camera_plan, output):
    import mujoco
    import numpy as np
    from OpenGL import GL
    from PIL import Image
    from mujoco.rendering.classic import renderer as classic
    from xbox_gamepad_physics.mujoco.loader import make_spec

    plan = json.loads(Path(camera_plan).read_text())
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    asset = make_spec(resource_root=resource_root, fixed_root=True)
    spec = asset.spec
    for name, view in plan["views"].items():
        pos = np.asarray(view["position_m"])
        forward = np.asarray(view["target_m"]) - pos
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, [0, 0, 1])
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        quat = np.empty(4)
        mujoco.mju_mat2Quat(quat, np.column_stack([right, up, -forward]).reshape(-1))
        spec.worldbody.add_camera(name=f"d2_{name}", pos=pos, quat=quat,
                                  fovy=view["fovy_degrees"])
    background = np.asarray(plan["background_linear"])
    background = np.where(background <= 0.0031308, 12.92 * background,
                          1.055 * background ** (1 / 2.4) - 0.055)
    spec.add_texture(name="d2_background", type=mujoco.mjtTexture.mjTEXTURE_SKYBOX,
                     builtin=mujoco.mjtBuiltin.mjBUILTIN_FLAT, rgb1=background,
                     rgb2=background, width=16, height=96)
    model = spec.compile()
    data = mujoco.MjData(model)
    gamepad = asset.bind(model, data)
    mujoco.mj_forward(model, data)
    model.stat.extent = 1
    model.vis.global_.offwidth = max(v["resolution"][0] for v in plan["views"].values())
    model.vis.global_.offheight = max(v["resolution"][1] for v in plan["views"].values())
    model.vis.quality.offsamples = 1
    model.vis.quality.shadowsize = 512
    model.vis.map.znear, model.vis.map.zfar = 0.001, 10
    model.vis.headlight.ambient[:] = 0.25
    model.vis.headlight.diffuse[:] = 0.7
    model.vis.headlight.specular[:] = 0.2
    record = {"version": mujoco.__version__, "renderer": "classic", "context": os.environ.get("MUJOCO_GL"),
              'backend_options': asset.manifest.get('backend_options'),
              "egl_device_id": os.environ.get("MUJOCO_EGL_DEVICE_ID"),
              "camera_plan": plan, "root_pose": "identity", "state": "common physical initial positions; no physics steps",
              "initial_positions": gamepad.joint_positions(),
              "physical_validation": False, "appearance_approved": None,
              "environment": "D2 headlight approximation; classic does not reproduce HDR IBL/PBR.",
              "headlight": {"ambient": 0.25, "diffuse": 0.7, "specular": 0.2},
              "material_rgba": model.mat_rgba.tolist(), "captures": []}
    for name, view in plan["views"].items():
        width, height = view["resolution"]
        with classic.Renderer(model, height=height, width=width) as renderer:
            gpu = GL.glGetString(GL.GL_RENDERER).decode()
            if "nvidia" not in GL.glGetString(GL.GL_VENDOR).decode().lower():
                raise RuntimeError(f"D2 delivery requires GPU EGL; renderer is {gpu}")
            renderer.update_scene(data, camera=f"d2_{name}")
            renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = False
            pixels = renderer.render().copy()
        raw = output / f"mujoco_{name}_raw.png"
        delivery = output / f"mujoco_{name}.png"
        image = Image.fromarray(pixels)
        image.save(raw)
        image.resize(tuple(view["delivery"]), Image.Resampling.LANCZOS).save(delivery)
        record["captures"].append({"view": name, "GL_RENDERER": gpu,
                                   "raw": str(raw.resolve()), "delivery": str(delivery.resolve())})
    (output / "render_settings.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-root", required=True)
    parser.add_argument("--camera-plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    os.environ["MUJOCO_GL"] = "egl"
    os.environ["MUJOCO_EGL_DEVICE_ID"] = "3"
    render(args.resource_root, args.camera_plan, args.output)


if __name__ == "__main__":
    main()
