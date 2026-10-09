"""Render per-group review frames from the full RoboTwin/SAPIEN articulation.

The canonical command is applied through SAPIEN drive targets.  Every trace
frame and on-screen value is then rebuilt from articulation qpos readback.
The script only prepares review material; it never marks an item accepted.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys


GROUPS = (
    "sticks",
    "face_buttons",
    "center_buttons",
    "shoulders_triggers",
    "dpad",
    "concurrent",
)


def pulse(channel: str, label: str, frames: int = 18):
    for index in range(frames):
        phase = index / (frames - 1)
        yield label, {channel: math.sin(math.pi * phase)}, 0.0


def circle(prefix: str, label: str, frames: int = 48):
    for index in range(frames):
        phase = index / (frames - 1)
        envelope = min(1.0, phase * 6.0, (1.0 - phase) * 6.0)
        angle = 2.0 * math.pi * phase
        yield label, {
            f"{prefix}_x": envelope * math.cos(angle),
            f"{prefix}_y": envelope * math.sin(angle),
        }, 0.0


def pair_pulse(label: str, frames: int = 18):
    for index in range(frames):
        phase = index / (frames - 1)
        yield label, {}, math.sin(math.pi * phase)


def dpad_direction(label: str, horizontal: float, vertical: float, frames: int = 18):
    values = {}
    if horizontal < 0:
        values["dpad_left"] = abs(horizontal)
    elif horizontal > 0:
        values["dpad_right"] = horizontal
    if vertical < 0:
        values["dpad_up"] = abs(vertical)
    elif vertical > 0:
        values["dpad_down"] = vertical
    for index in range(frames):
        phase = math.sin(math.pi * index / (frames - 1))
        yield label, {name: value * phase for name, value in values.items()}, 0.0


def sequence(group: str):
    if group == "sticks":
        yield from circle("left", "Left stick: full circle")
        yield from pulse("left_stick", "L3: stick click")
        yield from circle("right", "Right stick: full circle")
        yield from pulse("right_stick", "R3: stick click")
    elif group == "face_buttons":
        for channel, label in (
            ("south", "A / South"),
            ("east", "B / East"),
            ("west", "X / West"),
            ("north", "Y / North"),
        ):
            yield from pulse(channel, label)
    elif group == "center_buttons":
        for channel, label in (
            ("back", "View / Back"),
            ("start", "Menu / Start"),
            ("guide", "Xbox / Guide"),
        ):
            yield from pulse(channel, label)
        yield from pair_pulse("Pair / Bind (physical-only event)")
    elif group == "shoulders_triggers":
        for channel, label in (
            ("left_shoulder", "LB / Left shoulder"),
            ("right_shoulder", "RB / Right shoulder"),
            ("left_trigger", "LT / Left trigger"),
            ("right_trigger", "RT / Right trigger"),
        ):
            yield from pulse(channel, label)
    elif group == "dpad":
        for label, horizontal, vertical in (
            ("D-pad left", -1.0, 0.0),
            ("D-pad right", 1.0, 0.0),
            ("D-pad up", 0.0, -1.0),
            ("D-pad down", 0.0, 1.0),
            ("D-pad up-left", -math.sqrt(0.5), -math.sqrt(0.5)),
            ("D-pad down-right", math.sqrt(0.5), math.sqrt(0.5)),
        ):
            yield from dpad_direction(label, horizontal, vertical)
    elif group == "concurrent":
        frames = 72
        for index in range(frames):
            phase = index / (frames - 1)
            angle = 2.0 * math.pi * phase
            pulse_value = 0.5 - 0.5 * math.cos(4.0 * math.pi * phase)
            yield "Concurrent: sticks + triggers + A + LB + D-pad", {
                "left_x": 0.8 * math.cos(angle),
                "left_y": 0.8 * math.sin(angle),
                "right_x": 0.65 * math.cos(-1.5 * angle),
                "right_y": 0.65 * math.sin(-1.5 * angle),
                "left_trigger": phase,
                "right_trigger": 1.0 - phase,
                "south": pulse_value,
                "left_shoulder": 1.0 if 0.3 <= phase <= 0.7 else 0.0,
                "dpad_right": 1.0 if 0.45 <= phase <= 0.65 else 0.0,
            }, 0.0
    else:
        raise ValueError(f"unknown review group {group!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robotwin-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--physics-hz", type=int, default=240)
    parser.add_argument("--spp", type=int, default=8)
    parser.add_argument("--denoiser", choices=("none", "oidn", "optix"), default="oidn")
    parser.add_argument("--groups", nargs="+", choices=GROUPS, default=GROUPS)
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
    from xbox_gamepad_physics.state import (
        GamepadDeviceId,
        GamepadState,
        XBOX_ONE_S_CHANNELS,
    )

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
    gamepad = load_into_scene(
        scene,
        pose=sapien.Pose(p=[0, 0, 0.8]),
        fixed_root=True,
        profile="full_controls_estimated_v0",
    )
    camera = scene.add_camera(
        "full_controls_review", 1280, 720, math.radians(36), 0.001, 10
    )
    camera_positions = {
        "sticks": ([0.08, -0.30, 1.04], [0.0, 0.01, 0.79]),
        "face_buttons": ([0.14, -0.25, 1.00], [0.035, 0.02, 0.80]),
        "center_buttons": ([0.02, -0.27, 1.00], [0.0, 0.015, 0.80]),
        "shoulders_triggers": ([0.24, -0.27, 1.04], [0.0, 0.02, 0.80]),
        "dpad": ([-0.13, -0.25, 1.00], [-0.035, 0.01, 0.80]),
        "concurrent": ([0.10, -0.34, 1.06], [0.0, 0.01, 0.79]),
    }

    substeps = args.physics_hz // args.fps
    reports = []
    for group in args.groups:
        directory = output / group
        directory.mkdir(parents=True, exist_ok=True)
        position, target = camera_positions[group]
        camera.entity.set_pose(look_at(position, target))
        gamepad.set_joint_positions({name: 0.0 for name in gamepad.joint_names})
        gamepad.articulation.set_qvel(np.zeros(len(gamepad.joint_names)))
        observed_frames = []
        for frame_index, (label, command, pair_value) in enumerate(sequence(group)):
            target_state = GamepadState.from_mapping(
                command,
                device_id=GamepadDeviceId.XBOX_ONE_S,
                available_channels=XBOX_ONE_S_CHANNELS,
                task_channels=tuple(command),
            )
            for _ in range(substeps):
                gamepad.set_gamepad_targets(target_state)
                if pair_value:
                    gamepad.set_physical_events({"pair_bind_connect": pair_value})
                scene.step()

            observed = gamepad.gamepad_state(task_channels=tuple(command))
            events = gamepad.physical_events()
            qpos = gamepad.joint_positions()
            active = [
                f"{name}={observed.channel(name):+.2f}"
                for name in XBOX_ONE_S_CHANNELS
                if abs(observed.channel(name)) >= 0.05
            ]
            if events.get("pair_bind_connect", 0.0) >= 0.05:
                active.append(f"pair={events['pair_bind_connect']:.2f}")
            observed_frames.append(
                {
                    "layout_id": observed.layout_id,
                    "values": list(observed.values),
                    "available_mask": list(observed.available_mask),
                    "task_mask": list(observed.task_mask),
                    "device_id": observed.device_id,
                    "telemetry": {
                        "frame_index": frame_index,
                        "phase": label,
                        "target": command,
                        "pair_target": pair_value,
                        "pair_observed": events.get("pair_bind_connect", 0.0),
                        "qpos": qpos,
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
                f"RoboTwin / SAPIEN qpos readback | {label}",
                (34, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (245, 245, 245),
                2,
                cv2.LINE_AA,
            )
            active_text = "  ".join(active) if active else "neutral"
            cv2.putText(
                bgr,
                active_text[:105],
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
            cv2.imwrite(str(directory / f"frame_{frame_index:04d}.png"), bgr)

        trace = {
            "schema_version": 1,
            "review_group": group,
            "backend": "robotwin_sapien",
            "profile": "full_controls_estimated_v0",
            "stimulus": "canonical_state_to_sapien_drive_targets",
            "signal_source": "sapien_articulation_qpos_readback_after_physics_steps",
            "fps": args.fps,
            "physics_hz": args.physics_hz,
            "frame_count": len(observed_frames),
            "frames": observed_frames,
        }
        (directory / "observed_trace.json").write_text(
            json.dumps(trace, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        reports.append(
            {
                "group": group,
                "frames": len(observed_frames),
                "trace": f"{group}/observed_trace.json",
                "frame_pattern": f"{group}/frame_%04d.png",
            }
        )

    report = {
        "schema_version": 1,
        "backend": "robotwin_sapien",
        "sapien": sapien.__version__,
        "profile": "full_controls_estimated_v0",
        "renderer": "robotwin_rt",
        "samples_per_pixel": args.spp,
        "denoiser": args.denoiser,
        "gpu_visible": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "fps": args.fps,
        "physics_hz": args.physics_hz,
        "groups": reports,
        "acceptance": "pending_user_review",
    }
    (output / "render_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
