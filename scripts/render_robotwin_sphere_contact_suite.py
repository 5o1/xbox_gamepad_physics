#!/usr/bin/env python3
"""Render per-control RoboTwin sphere contacts with qpos-derived gamepad traces."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sys


@dataclass(frozen=True)
class ContactCase:
    key: str
    group: str
    label: str
    channel: str
    joint: str
    link: str
    motion: str
    direction: tuple[float, float, float] | None = None


CONTACT_CASES = (
    ContactCase("left_stick", "sticks", "Left stick tilt", "left_x", "left_stick_x", "left_stick", "stick_tilt", (1, 0, 0)),
    ContactCase("right_stick", "sticks", "Right stick tilt", "right_x", "right_stick_x", "right_stick", "stick_tilt", (1, 0, 0)),
    ContactCase("button_a", "buttons", "A / South button", "south", "a_press", "a", "top_press"),
    ContactCase("button_b", "buttons", "B / East button", "east", "b_press", "b", "top_press"),
    ContactCase("button_x", "buttons", "X / West button", "west", "x_press", "x", "top_press"),
    ContactCase("button_y", "buttons", "Y / North button", "north", "y_press", "y", "top_press"),
    ContactCase("button_view", "buttons", "View / Back button", "back", "view_press", "view", "top_press"),
    ContactCase("button_menu", "buttons", "Menu / Start button", "start", "menu_press", "menu", "top_press"),
    ContactCase("button_guide", "buttons", "Xbox / Guide button", "guide", "guide_press", "guide", "top_press"),
    ContactCase("button_l3", "buttons", "L3 / Left-stick click", "left_stick", "left_stick_click", "left_stick", "stick_click"),
    ContactCase("button_r3", "buttons", "R3 / Right-stick click", "right_stick", "right_stick_click", "right_stick", "stick_click"),
    ContactCase("dpad_left", "dpad", "D-pad left", "dpad_left", "dpad_horizontal", "dpad", "dpad_press", (-1, 0, 0)),
    ContactCase("dpad_right", "dpad", "D-pad right", "dpad_right", "dpad_horizontal", "dpad", "dpad_press", (1, 0, 0)),
    ContactCase("dpad_up", "dpad", "D-pad up", "dpad_up", "dpad_vertical", "dpad", "dpad_press", (0, 1, 0)),
    ContactCase("dpad_down", "dpad", "D-pad down", "dpad_down", "dpad_vertical", "dpad", "dpad_press", (0, -1, 0)),
    ContactCase("shoulder_left", "shoulders", "LB / Left shoulder", "left_shoulder", "left_shoulder_press", "left_shoulder", "side_press", (0, -1, 0)),
    ContactCase("shoulder_right", "shoulders", "RB / Right shoulder", "right_shoulder", "right_shoulder_press", "right_shoulder", "side_press", (0, -1, 0)),
    ContactCase("trigger_left", "triggers", "LT / Left trigger", "left_trigger", "left_trigger_hinge", "left_trigger", "trigger_press"),
    ContactCase("trigger_right", "triggers", "RT / Right trigger", "right_trigger", "right_trigger_hinge", "right_trigger", "trigger_press"),
)

CASE_BY_KEY = {case.key: case for case in CONTACT_CASES}


def ease(value: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * value)


def frame_phase(index: int, *, lead: int, push: int, hold: int, release: int):
    if index < lead:
        return "ready", 0.0
    index -= lead
    if index < push:
        return "sphere push", ease(index / max(1, push - 1))
    index -= push
    if index < hold:
        return "contact hold", 1.0
    index -= hold
    return "release / passive return", 1.0 - ease(index / max(1, release - 1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robotwin-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root-mode", choices=("fixed", "free"), required=True)
    parser.add_argument("--tests", nargs="+", choices=tuple(CASE_BY_KEY), default=tuple(CASE_BY_KEY))
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--physics-hz", type=int, default=240)
    parser.add_argument("--spp", type=int, default=4)
    parser.add_argument("--denoiser", choices=("none", "oidn", "optix"), default="oidn")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()
    if args.physics_hz % args.fps:
        raise ValueError("physics-hz must be divisible by fps")

    robotwin_root = args.robotwin_root.resolve()
    package_root = args.package_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(package_root), str(robotwin_root)]
    os.chdir(robotwin_root)

    import cv2
    import numpy as np
    import sapien
    from transforms3d.quaternions import mat2quat

    from envs._base_task import Base_Task, create_box, create_table
    from xbox_gamepad_physics import load_motion_contract
    from xbox_gamepad_physics.resources import load_json_resource
    from xbox_gamepad_physics.robotwin import load_into_scene

    def look_at(position, target):
        forward = np.asarray(target, dtype=float) - np.asarray(position, dtype=float)
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
        color=(0.76, 0.79, 0.83),
        name="review_wall",
        is_static=True,
    )
    table_height = 0.74
    create_table(
        scene,
        sapien.Pose(p=[0, 0, table_height]),
        length=1.2,
        width=0.7,
        height=table_height,
        thickness=0.05,
        color=(0.20, 0.27, 0.31),
        name="review_table",
        is_static=True,
    )
    collision = load_json_resource("robotwin", "full_controls", "collision/manifest.json")
    root_geom = collision["links"]["controller_body"][0]
    root_bottom = root_geom["center"][2] - root_geom["size"][2] / 2
    root_position = np.array([0.0, 0.0, table_height - root_bottom + 0.0005])
    root_pose = sapien.Pose(p=root_position)
    gamepad = load_into_scene(
        scene,
        pose=root_pose,
        fixed_root=args.root_mode == "fixed",
        profile="full_controls",
    )

    probe_radius = 0.006
    probe_material = sapien.render.RenderMaterial(
        base_color=[1.0, 0.02, 0.02, 1.0], roughness=0.25, metallic=0.0, specular=0.5
    )
    physical_material = scene.create_physical_material(0.5, 0.4, 0.05)
    builder = scene.create_actor_builder()
    builder.add_sphere_collision(radius=probe_radius, material=physical_material)
    builder.add_sphere_visual(radius=probe_radius, material=probe_material)
    park = root_position + np.array([0.0, -0.18, 0.18])
    builder.set_initial_pose(sapien.Pose(park))
    probe_name = "gamepad_contact_probe"
    probe = builder.build_kinematic(name=probe_name)

    cameras = []
    camera_records = (
        ("front", root_position + np.array([0.0, -0.30, 0.17]), root_position + np.array([0.0, 0.005, 0.004])),
        ("top", root_position + np.array([0.0, -0.015, 0.34]), root_position + np.array([0.0, 0.005, 0.0])),
        ("left_oblique", root_position + np.array([-0.27, -0.20, 0.17]), root_position + np.array([0.0, 0.005, 0.0])),
    )
    if not args.no_render:
        for name, position, target in camera_records:
            camera = scene.add_camera(name, args.width, args.height, math.radians(40), 0.001, 10)
            camera.entity.set_pose(look_at(position, target))
            cameras.append((name, camera))

    motion = load_motion_contract("full_controls")
    def link(name):
        result = gamepad.articulation.find_link_by_name(name)
        if result is None:
            raise RuntimeError(f"missing link {name}")
        return result

    def link_pose(name):
        component = link(name)
        entity = getattr(component, "entity", None)
        if entity is None:
            getter = getattr(component, "get_entity", None)
            entity = getter() if callable(getter) else None
        pose = getattr(entity, "pose", None)
        if pose is None:
            getter = getattr(entity, "get_pose", None)
            pose = getter() if callable(getter) else None
        if pose is None:
            raise RuntimeError(f"link {name} exposes no world pose")
        return pose

    def to_world(name, local_point):
        matrix = link_pose(name).to_transformation_matrix()
        local = np.asarray(local_point, dtype=float)
        return matrix[:3, :3] @ local + matrix[:3, 3]

    def reset_articulation():
        gamepad.set_joint_positions({name: 0.0 for name in gamepad.joint_names})
        gamepad.articulation.set_qvel(np.zeros(len(gamepad.joint_names)))
        setter = getattr(gamepad.articulation, "set_root_pose", None)
        if not callable(setter):
            setter = gamepad.articulation.set_pose
        setter(root_pose)
        for method_name in ("set_root_linear_velocity", "set_root_angular_velocity"):
            method = getattr(gamepad.articulation, method_name, None)
            if callable(method):
                method(np.zeros(3))
        probe.set_pose(sapien.Pose(park))
        for _ in range(args.physics_hz // 2):
            scene.step()

    def path_for(case):
        geoms = collision["links"][case.link]
        if case.motion == "stick_tilt":
            sign = np.asarray(case.direction, dtype=float)
            return to_world(case.link, sign * np.array([0.030, 0.030, 0.0]) + np.array([0, 0, 0.016])), to_world(case.link, sign * np.array([0.010, 0.010, 0.0]) + np.array([0, 0, 0.016]))
        if case.motion == "stick_click":
            return to_world(case.link, [0, 0, 0.032]), to_world(case.link, [0, 0, 0.021])
        geom = geoms[0]
        center = np.asarray(geom["center"], dtype=float)
        if case.motion == "top_press":
            surface = center + np.array([0, 0, geom["length"] / 2])
            travel = motion.joint_by_name[case.joint].upper
            return to_world(case.link, surface + np.array([0, 0, probe_radius + 0.008])), to_world(case.link, surface + np.array([0, 0, probe_radius - travel - 0.001]))
        if case.motion == "side_press":
            direction = np.asarray(case.direction, dtype=float)
            support = np.dot(np.abs(direction), np.asarray(geom["size"], dtype=float) / 2)
            surface = center - direction * support
            travel = motion.joint_by_name[case.joint].upper
            return to_world(case.link, surface - direction * (probe_radius + 0.008)), to_world(case.link, surface - direction * (probe_radius - travel - 0.0015))
        if case.motion == "dpad_press":
            direction = np.asarray(case.direction, dtype=float)
            surface = center + direction * 0.007 + np.array([0, 0, geom["size"][2] / 2])
            return to_world(case.link, surface + np.array([0, 0, probe_radius + 0.008])), to_world(case.link, surface + np.array([0, 0, probe_radius - 0.004]))
        if case.motion == "trigger_press":
            axis = np.asarray((-1.0, 0.0, 0.0))
            direction = np.cross(axis, center)
            direction /= np.linalg.norm(direction)
            support = np.dot(np.abs(direction), np.asarray(geom["size"], dtype=float) / 2)
            surface = center - direction * support
            return to_world(case.link, surface - direction * (probe_radius + 0.008)), to_world(case.link, surface - direction * (probe_radius - 0.006))
        raise RuntimeError(f"unknown contact motion {case.motion}")

    def root_state():
        getter = getattr(gamepad.articulation, "get_root_pose", None)
        if not callable(getter):
            getter = gamepad.articulation.get_pose
        pose = getter()
        return np.asarray(pose.p, dtype=float), np.asarray(pose.q, dtype=float)

    def probe_contacts():
        count = 0
        for contact in scene.get_contacts():
            names = {
                getattr(getattr(body, "entity", None), "name", None)
                for body in getattr(contact, "bodies", ())
            }
            count += probe_name in names
        return count

    substeps = args.physics_hz // args.fps
    counts = {"lead": 4, "push": 12, "hold": 6, "release": 12}
    total_frames = sum(counts.values())
    reports = []
    for key in args.tests:
        case = CASE_BY_KEY[key]
        reset_articulation()
        start, end = path_for(case)
        initial_root, _ = root_state()
        directory = output / args.root_mode / case.key
        frames_directory = directory / "frames"
        if not args.no_render:
            frames_directory.mkdir(parents=True, exist_ok=True)
        observed_frames = []
        peak_signal = 0.0
        contact_frames = 0
        peak_root_displacement = 0.0
        for frame_index in range(total_frames):
            phase, amount = frame_phase(frame_index, **counts)
            position = start * (1 - amount) + end * amount
            for _ in range(substeps):
                probe.set_pose(sapien.Pose(position))
                for item in gamepad.articulation.get_links():
                    item.wake_up()
                scene.step()
            contacts = probe_contacts()
            state = gamepad.gamepad_state(task_channels=(case.channel,))
            qpos = gamepad.joint_positions()
            current_root, root_quaternion = root_state()
            signal = state.channel(case.channel)
            peak_signal = max(peak_signal, abs(signal))
            contact_frames += contacts > 0
            root_displacement = float(np.linalg.norm(current_root - initial_root))
            peak_root_displacement = max(peak_root_displacement, root_displacement)
            observed_frames.append(
                {
                    "layout_id": state.layout_id,
                    "values": list(state.values),
                    "available_mask": list(state.available_mask),
                    "task_mask": list(state.task_mask),
                    "device_id": state.device_id,
                    "telemetry": {
                        "frame_index": frame_index,
                        "phase": phase,
                        "test_key": case.key,
                        "test_label": case.label,
                        "root_mode": args.root_mode,
                        "probe_position_m": position.tolist(),
                        "contacts": contacts,
                        "channel": case.channel,
                        "signal": signal,
                        "joint": case.joint,
                        "joint_qpos": qpos[case.joint],
                        "root_position_m": current_root.tolist(),
                        "root_quaternion_wxyz": root_quaternion.tolist(),
                        "root_displacement_m": root_displacement,
                    },
                }
            )
            if args.no_render:
                continue
            scene.update_render()
            views = []
            for camera_name, camera in cameras:
                camera.take_picture()
                rgba = camera.get_picture("Color")
                bgr = np.ascontiguousarray(
                    np.rint(np.clip(rgba[..., :3], 0, 1) * 255).astype(np.uint8)[..., ::-1]
                )
                cv2.rectangle(bgr, (0, args.height - 30), (180, args.height), (18, 24, 29), -1)
                cv2.putText(bgr, camera_name, (12, args.height - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (235, 240, 245), 1, cv2.LINE_AA)
                views.append(bgr)
            tri = np.concatenate(views, axis=1)
            canvas = np.full((args.height + 72, args.width * 3, 3), (18, 24, 29), np.uint8)
            canvas[72:] = tri
            mode_label = "FIXED ROOT" if args.root_mode == "fixed" else "FREE ROOT / PUSHABLE"
            cv2.putText(canvas, f"RoboTwin sphere contact | {mode_label} | {case.label}", (22, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (245, 245, 245), 2, cv2.LINE_AA)
            cv2.putText(canvas, f"{phase} | contacts={contacts} | {case.channel}={signal:+.3f} | qpos={qpos[case.joint]:+.5f} | root motion={root_displacement*1000:.2f} mm", (22, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (65, 220, 255), 1, cv2.LINE_AA)
            cv2.imwrite(str(frames_directory / f"frame_{frame_index:04d}.png"), canvas)

        trace = {
            "schema_version": 1,
            "backend": "robotwin_sapien",
            "profile": "full_controls",
            "root_mode": args.root_mode,
            "review_group": case.group,
            "test_key": case.key,
            "test_label": case.label,
            "channel": case.channel,
            "joint": case.joint,
            "stimulus": "kinematic_sphere_collision_only",
            "signal_source": "sapien_articulation_qpos_readback_after_every_physics_tick",
            "commanded_gamepad_state_during_recording": False,
            "fps": args.fps,
            "physics_hz": args.physics_hz,
            "frame_count": len(observed_frames),
            "contact_video_frames": contact_frames,
            "peak_abs_signal": peak_signal,
            "peak_root_displacement_m": peak_root_displacement,
            "frames": observed_frames,
        }
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "observed_trace.json").write_text(json.dumps(trace, separators=(",", ":")) + "\n", encoding="utf-8")
        reports.append({key: value for key, value in trace.items() if key != "frames"})
        print(json.dumps(reports[-1]), flush=True)

    report = {
        "schema_version": 1,
        "backend": "robotwin_sapien",
        "sapien": sapien.__version__,
        "profile": "full_controls",
        "root_mode": args.root_mode,
        "table_top_z_m": table_height,
        "initial_root_position_m": root_position.tolist(),
        "signal_source": "sapien_articulation_qpos_readback_after_every_physics_tick",
        "probe_actuation": "kinematic_sphere_collision_only",
        "commanded_gamepad_state_during_recording": False,
        "renderer": None if args.no_render else "robotwin_rt_three_camera",
        "samples_per_pixel": None if args.no_render else args.spp,
        "camera_names": [item[0] for item in camera_records],
        "tests": reports,
        "acceptance": "pending_user_review",
    }
    (output / args.root_mode / "render_manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"root_mode": args.root_mode, "tests": len(reports), "output": str(output / args.root_mode)}))


if __name__ == "__main__":
    main()
