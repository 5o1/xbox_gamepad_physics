"""Validate the estimated Xbox One S left-stick articulation in SAPIEN."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps-per-second", type=int, default=240)
    parser.add_argument("--no-contact-probe", action="store_true")
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--render-fps", type=int, default=30)
    parser.add_argument("--spp", type=int, default=8)
    args = parser.parse_args()

    import cv2
    import numpy as np
    import sapien
    from transforms3d.quaternions import mat2quat

    from xbox_gamepad_physics.robotwin import load_into_scene

    if args.render_dir:
        sapien.render.set_camera_shader_dir("rt")
        sapien.render.set_ray_tracing_samples_per_pixel(args.spp)
        sapien.render.set_ray_tracing_path_depth(4)
    scene = sapien.Scene()
    scene.set_timestep(1.0 / args.steps_per_second)
    scene.set_ambient_light([0.25, 0.25, 0.25])
    scene.add_directional_light([0.4, 0.5, -1], [1.2, 1.2, 1.2], shadow=True)
    gamepad = load_into_scene(
        scene,
        pose=sapien.Pose(),
        fixed_root=True,
        profile="left_stick_estimated_v0",
    )
    limit = math.radians(23.0)

    samples = {}
    for name, qpos in {
        "neutral": (0.0, 0.0),
        "positive_x": (limit, 0.0),
        "negative_y": (0.0, -limit),
        "diagonal_joint_corner": (limit, limit),
    }.items():
        gamepad.set_joint_positions(
            {"left_stick_x": qpos[0], "left_stick_y": qpos[1]}
        )
        state = gamepad.gamepad_state()
        samples[name] = {
            "qpos": list(qpos),
            "lx": state.lx,
            "ly": state.ly,
            "signal_radius": math.hypot(state.lx, state.ly),
        }

    articulation = gamepad.articulation
    gamepad.set_joint_positions({"left_stick_x": 0.2, "left_stick_y": -0.1})
    articulation.set_qvel(np.zeros(2))
    return_trace = []
    for index in range(2 * args.steps_per_second):
        scene.step()
        if index % max(1, args.steps_per_second // 20) == 0:
            return_trace.append(gamepad.joint_positions())

    contact_report = {"executed": False}
    render_report = None
    if not args.no_contact_probe:
        gamepad.set_joint_positions({"left_stick_x": 0.0, "left_stick_y": 0.0})
        articulation.set_qvel(np.zeros(2))
        for link in articulation.get_links():
            link.wake_up()
        material = scene.create_physical_material(0.5, 0.4, 0.05)
        probe_visual = sapien.render.RenderMaterial(
            base_color=[1.0, 0.015, 0.015, 1.0],
            roughness=0.28,
            metallic=0.0,
            specular=0.5,
        )
        pivot = np.array([-0.038035359991741326, 0.024133629044164898, 0.01212386322086352])
        start = pivot + np.array([0.027, 0.0, 0.016])
        end = pivot + np.array([0.011, 0.0, 0.016])
        builder = scene.create_actor_builder()
        builder.add_sphere_collision(radius=0.006, material=material)
        builder.add_sphere_visual(radius=0.006, material=probe_visual)
        builder.set_initial_pose(sapien.Pose(start))
        pusher = builder.build_kinematic(name="left_stick_contact_probe")
        camera = None
        writer = None
        frame_paths = []
        frame_stride = max(1, args.steps_per_second // args.render_fps)
        if args.render_dir:
            args.render_dir.mkdir(parents=True, exist_ok=True)

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

            camera = scene.add_camera(
                "left_stick_contact_camera", 720, 540, math.radians(34), 0.001, 2.0
            )
            camera.entity.set_pose(
                look_at(pivot + np.array([0.075, -0.13, 0.085]), pivot + np.array([0, 0, 0.011]))
            )
            video_path = args.render_dir / "left_stick_contact_probe.mp4"
            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                args.render_fps,
                (720, 540),
            )
            if not writer.isOpened():
                raise RuntimeError(f"cannot open video writer: {video_path}")

        def capture(phase, step):
            if camera is None or writer is None:
                return
            scene.update_render()
            camera.take_picture()
            rgba = camera.get_picture("Color")
            bgr = np.ascontiguousarray(
                np.rint(np.clip(rgba[..., :3], 0, 1) * 255)
                .astype(np.uint8)[..., ::-1]
            )
            qpos = gamepad.joint_positions()
            state = gamepad.gamepad_state()
            cv2.putText(
                bgr,
                f"{phase}  qx={qpos['left_stick_x']:+.3f} rad  qy={qpos['left_stick_y']:+.3f} rad",
                (22, 34),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.68,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                bgr,
                f"gamepad: lx={state.lx:+.3f}  ly={state.ly:+.3f}",
                (22, 64),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.68,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            writer.write(np.ascontiguousarray(bgr))
            if step in {0, args.steps_per_second // 2, args.steps_per_second - 1}:
                path = args.render_dir / f"{phase}_{step:04d}.png"
                cv2.imwrite(str(path), bgr)
                frame_paths.append(path.name)

        trace = []
        contact_frames = 0
        for index in range(args.steps_per_second):
            alpha = index / (args.steps_per_second - 1)
            position = start * (1.0 - alpha) + end * alpha
            pusher.set_pose(sapien.Pose(position))
            for link in articulation.get_links():
                link.wake_up()
            scene.step()
            qpos = gamepad.joint_positions()
            trace.append(qpos)
            if scene.get_contacts():
                contact_frames += 1
            if index % frame_stride == 0 or index == args.steps_per_second - 1:
                capture("push", index)
        peak = max(abs(item["left_stick_x"]) for item in trace)
        pusher.set_pose(sapien.Pose(start))
        for index in range(args.steps_per_second):
            scene.step()
            if index % frame_stride == 0 or index == args.steps_per_second - 1:
                capture("release", index)
        if writer is not None:
            writer.release()
            render_report = {
                "video": "left_stick_contact_probe.mp4",
                "frames": frame_paths,
                "fps": args.render_fps,
                "resolution": [720, 540],
                "samples_per_pixel": args.spp,
            }
        contact_report = {
            "executed": True,
            "contact_frames": contact_frames,
            "peak_abs_left_stick_x_rad": peak,
            "state_at_peak_bound": peak / limit,
            "released_qpos": gamepad.joint_positions(),
        }

    report = {
        "sapien": sapien.__version__,
        "profile": "left_stick_estimated_v0",
        "timestep": scene.get_timestep(),
        "joint_names": list(gamepad.joint_names),
        "samples": samples,
        "passive_return": {
            "initial": {"left_stick_x": 0.2, "left_stick_y": -0.1},
            "trace": return_trace,
            "final": gamepad.joint_positions() if args.no_contact_probe else return_trace[-1],
        },
        "contact_probe": contact_report,
        "render": render_report,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
