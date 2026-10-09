"""Render a real MuJoCo contact push and release with signal readback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from render_mujoco_full_controls_review import build_review_xml


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--physics-hz", type=int, default=240)
    parser.add_argument("--graphics", default="vulkan")
    args = parser.parse_args()
    if args.physics_hz % args.fps:
        raise ValueError("physics-hz must be divisible by fps")

    package_root = args.package_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(package_root))

    import mujoco
    import mujoco._render_filament as mjrf
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from mujoco.experimental.studio import window
    from mujoco.rendering.filament import renderer as filament_renderer

    from xbox_gamepad_physics.mujoco._manifest import load_runtime_manifest
    from xbox_gamepad_physics.mujoco.handle import bind_handle

    runtime_xml = build_review_xml(
        package_root,
        output / "_runtime",
        source_filename="scene_contact_probe.xml",
    )
    model = mujoco.MjModel.from_xml_path(str(runtime_xml))
    data = mujoco.MjData(model)
    manifest = load_runtime_manifest("full_controls_estimated_v0")
    handle = bind_handle(
        model,
        data,
        joints=manifest.joints,
        sensors=manifest.sensors,
        signal_controller=manifest.signal_controller,
    )
    probe_body = model.body("left_stick_contact_probe")
    mocap_id = int(model.body_mocapid[probe_body.id])
    if mocap_id < 0:
        raise RuntimeError("left-stick contact probe is not a mocap body")
    pivot = np.array(
        [-0.0380353599917, 0.0241336290442, 0.0121238632209], dtype=float
    )
    start = pivot + np.array([0.027, 0.0, 0.016])
    end = pivot + np.array([0.011, 0.0, 0.016])
    data.mocap_pos[mocap_id] = start
    data.mocap_quat[mocap_id] = [1, 0, 0, 0]
    mujoco.mj_forward(model, data)

    api = (
        mjrf.GraphicsApi.GRAPHICS_API_VULKAN
        if args.graphics.startswith("vulkan")
        else mjrf.GraphicsApi.GRAPHICS_API_OPENGL
    )
    resource_window = window.Window("Xbox contact review", 32, 32, args.graphics)
    context = mjrf.Context(mjrf.ContextConfig(graphics_api=api))
    renderer = filament_renderer.Renderer(context)
    objects = mjrf.ModelObjects(context, model)
    scene = renderer.scene("xbox_contact_review")
    scene.configure_from_model(model)
    lights = mjrf.ModelLights(scene, objects)
    renderables = mjrf.ModelRenderables(scene, objects)
    options = mujoco.MjvOption()
    options.geomgroup[:] = 0
    options.geomgroup[1] = 1
    options.geomgroup[2] = 1
    options.geomgroup[3] = 1
    renderables.set_options(options)
    pixels = np.empty((720, 1280, 3), dtype=np.uint8)
    renderer.target("rgb", pixels)
    renderer.view("main", scene="xbox_contact_review", target="rgb")
    camera = mujoco.MjvCamera()
    camera.type = int(mujoco.mjtCamera.mjCAMERA_FIXED)
    camera.fixedcamid = model.camera("review_camera").id
    renderer.update_camera("main", mujoco.mjv_camera2GLCamera(model, data, camera))

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    title_font = ImageFont.truetype(font_path, 24)
    value_font = ImageFont.truetype(font_path, 18)
    substeps = args.physics_hz // args.fps
    push_frames = 60
    release_frames = 60
    trace_frames = []
    peak_signal = 0.0
    contact_frames = 0

    for frame_index in range(push_frames + release_frames):
        if frame_index < push_frames:
            phase = frame_index / (push_frames - 1)
            position = start * (1.0 - phase) + end * phase
            label = "contact push"
        else:
            position = start
            label = "release and passive return"
        for _ in range(substeps):
            data.mocap_pos[mocap_id] = position
            mujoco.mj_step(model, data)

        state = handle.gamepad_state(task_channels=("left_x", "left_y"))
        qpos = handle.joint_positions()
        if data.ncon:
            contact_frames += 1
        peak_signal = max(peak_signal, abs(state.channel("left_x")))
        trace_frames.append(
            {
                "layout_id": state.layout_id,
                "values": list(state.values),
                "available_mask": list(state.available_mask),
                "task_mask": list(state.task_mask),
                "device_id": state.device_id,
                "telemetry": {
                    "frame_index": frame_index,
                    "phase": label,
                    "probe_position_m": position.tolist(),
                    "contacts": int(data.ncon),
                    "left_stick_x_rad": qpos["left_stick_x"],
                    "left_stick_y_rad": qpos["left_stick_y"],
                },
            }
        )

        lights.update(data)
        renderables.update(data)
        renderer.render()
        image = Image.fromarray(pixels.copy())
        draw = ImageDraw.Draw(image, "RGBA")
        draw.rectangle((18, 17, 935, 112), fill=(24, 27, 31, 235))
        draw.text(
            (34, 29),
            f"MuJoCo physical contact | {label}",
            font=title_font,
            fill=(245, 245, 245, 255),
        )
        draw.text(
            (34, 63),
            f"contacts={data.ncon}  left_x={state.channel('left_x'):+.3f}  "
            f"qpos={qpos['left_stick_x']:+.4f} rad",
            font=value_font,
            fill=(80, 220, 255, 255),
        )
        draw.text(
            (34, 89),
            f"frame {frame_index:04d} | physics {args.physics_hz} Hz | video {args.fps} fps",
            font=value_font,
            fill=(205, 210, 215, 255),
        )
        image.save(output / f"frame_{frame_index:04d}.png")

    trace = {
        "schema_version": 1,
        "review_group": "left_stick_contact",
        "backend": "mujoco_filament",
        "profile": "full_controls_estimated_v0",
        "stimulus": "mocap_sphere_contact_then_release",
        "signal_source": "mujoco_qpos_readback_after_mj_step",
        "fps": args.fps,
        "physics_hz": args.physics_hz,
        "frame_count": len(trace_frames),
        "contact_video_frames": contact_frames,
        "peak_abs_left_x": peak_signal,
        "final_left_x": trace_frames[-1]["values"][0],
        "frames": trace_frames,
        "acceptance": "pending_user_review",
    }
    (output / "observed_trace.json").write_text(
        json.dumps(trace, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "frames": len(trace_frames),
                "contact_video_frames": contact_frames,
                "peak_abs_left_x": peak_signal,
                "final_left_x": trace["final_left_x"],
                "signal_source": trace["signal_source"],
            }
        )
    )
    del resource_window


if __name__ == "__main__":
    main()
