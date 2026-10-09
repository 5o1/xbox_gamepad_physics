"""Render a real SAPIEN contact push and passive left-stick return."""

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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--physics-hz", type=int, default=240)
    parser.add_argument("--spp", type=int, default=8)
    parser.add_argument("--denoiser", choices=("none", "oidn", "optix"), default="oidn")
    args = parser.parse_args()
    if args.physics_hz % args.fps:
        raise ValueError("physics-hz must be divisible by fps")

    robotwin_root = args.robotwin_root.resolve()
    package_root = args.package_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(package_root))
    sys.path.insert(0, str(robotwin_root))
    os.chdir(robotwin_root)

    import cv2
    import numpy as np
    import sapien
    from transforms3d.quaternions import mat2quat

    from envs._base_task import Base_Task, create_box, create_table
    from xbox_gamepad_physics.robotwin import load_into_scene
    from xbox_gamepad_physics.resources import load_json_resource

    def look_at(position, target):
        forward = np.asarray(target) - np.asarray(position)
        forward /= np.linalg.norm(forward)
        left = np.cross([0, 0, 1], forward)
        left /= np.linalg.norm(left)
        up = np.cross(forward, left)
        return sapien.Pose(p=position, q=mat2quat(np.column_stack([forward, left, up])))

    task = Base_Task()
    task.render_freq = 0
    task.random_light = False
    task.setup_scene()
    sapien.render.set_ray_tracing_denoiser(args.denoiser)
    sapien.render.set_ray_tracing_samples_per_pixel(args.spp)
    scene = task.scene
    scene.set_timestep(1.0 / args.physics_hz)
    create_box(
        scene,
        sapien.Pose(p=[0, 1, 1.5]),
        half_size=[3, 0.6, 1.5],
        color=(0.82, 0.84, 0.87),
        name="review_wall",
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
        name="review_table",
        is_static=True,
    )
    root_position = np.array([0.0, 0.0, 0.8])
    gamepad = load_into_scene(
        scene,
        pose=sapien.Pose(p=root_position),
        fixed_root=True,
        profile="full_controls",
    )
    pivot = root_position + np.array(
        [-0.0380353599917, 0.0241336290442, 0.0121238632209]
    )
    start = pivot + np.array([0.027, 0.0, 0.016])
    end = pivot + np.array([0.011, 0.0, 0.016])
    park = pivot + np.array([0.060, -0.040, 0.050])
    material = scene.create_physical_material(0.5, 0.4, 0.05)
    probe_material = sapien.render.RenderMaterial(
        base_color=[1.0, 0.015, 0.015, 1.0],
        roughness=0.28,
        metallic=0.0,
        specular=0.5,
    )
    builder = scene.create_actor_builder()
    builder.add_sphere_collision(radius=0.006, material=material)
    builder.add_sphere_visual(radius=0.006, material=probe_material)
    builder.set_initial_pose(sapien.Pose(start))
    probe = builder.build_kinematic(name="left_stick_contact_probe")
    camera = scene.add_camera(
        "contact_review", 1280, 720, math.radians(35), 0.001, 10
    )
    visual_scale = load_json_resource(
        "common", "xbox_one_s", "visual/manifest.json"
    )["meters_per_native_unit"]
    front_position = root_position + visual_scale * np.array(
        [-0.037516698241233826, -0.5597505569458008, 4.206621170043945]
    )
    front_target = root_position + visual_scale * np.array(
        [-0.037516698241233826, 0.24024944007396698, -0.2933788597583771]
    )
    camera.entity.set_pose(look_at(front_position, front_target))

    gamepad.set_joint_positions({name: 0.0 for name in gamepad.joint_names})
    gamepad.articulation.set_qvel(np.zeros(len(gamepad.joint_names)))
    substeps = args.physics_hz // args.fps
    push_frames = 60
    release_frames = 60
    trace_frames = []
    contact_video_frames = 0
    peak_signal = 0.0
    for frame_index in range(push_frames + release_frames):
        if frame_index < push_frames:
            phase = frame_index / (push_frames - 1)
            position = start * (1.0 - phase) + end * phase
            label = "contact push"
        else:
            position = park
            label = "release and passive return"
        for _ in range(substeps):
            probe.set_pose(sapien.Pose(position))
            for link in gamepad.articulation.get_links():
                link.wake_up()
            scene.step()

        contacts = [
            contact
            for contact in scene.get_contacts()
            if any(
                getattr(getattr(body, "entity", None), "name", None)
                == "left_stick_contact_probe"
                for body in getattr(contact, "bodies", ())
            )
        ]
        state = gamepad.gamepad_state(task_channels=("left_x", "left_y"))
        qpos = gamepad.joint_positions()
        if contacts:
            contact_video_frames += 1
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
                    "contacts": len(contacts),
                    "left_stick_x_rad": qpos["left_stick_x"],
                    "left_stick_y_rad": qpos["left_stick_y"],
                },
            }
        )

        scene.update_render()
        camera.take_picture()
        rgba = camera.get_picture("Color")
        bgr = np.ascontiguousarray(
            np.rint(np.clip(rgba[..., :3], 0, 1) * 255)
            .astype(np.uint8)[..., ::-1]
        )
        cv2.rectangle(bgr, (18, 17), (935, 112), (24, 27, 31), -1)
        cv2.putText(
            bgr,
            f"RoboTwin / SAPIEN physical contact | {label}",
            (34, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (245, 245, 245),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            bgr,
            f"contacts={len(contacts)}  left_x={state.channel('left_x'):+.3f}  "
            f"qpos={qpos['left_stick_x']:+.4f} rad",
            (34, 84),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (80, 220, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            bgr,
            f"frame {frame_index:04d} | physics {args.physics_hz} Hz | video {args.fps} fps",
            (34, 105),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (205, 210, 215),
            1,
            cv2.LINE_AA,
        )
        cv2.imwrite(str(output / f"frame_{frame_index:04d}.png"), bgr)

    trace = {
        "schema_version": 1,
        "review_group": "left_stick_contact",
        "backend": "robotwin_sapien",
        "profile": "full_controls",
        "stimulus": "kinematic_sphere_contact_then_release",
        "signal_source": "sapien_articulation_qpos_readback_after_physics_steps",
        "fps": args.fps,
        "physics_hz": args.physics_hz,
        "frame_count": len(trace_frames),
        "contact_video_frames": contact_video_frames,
        "peak_abs_left_x": peak_signal,
        "final_left_x": trace_frames[-1]["values"][0],
        "frames": trace_frames,
        "acceptance": "pending_user_review",
        "camera": {
            "name": "approved_front",
            "position_m": front_position.tolist(),
            "target_m": front_target.tolist(),
            "vertical_fov_degrees": 35,
        },
    }
    (output / "observed_trace.json").write_text(
        json.dumps(trace, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "frames": len(trace_frames),
                "contact_video_frames": contact_video_frames,
                "peak_abs_left_x": peak_signal,
                "final_left_x": trace["final_left_x"],
                "signal_source": trace["signal_source"],
                "gpu_visible": os.environ.get("CUDA_VISIBLE_DEVICES"),
            }
        )
    )


if __name__ == "__main__":
    main()
