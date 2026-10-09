"""Run SAPIEN stability/contact sensitivity checks for the left-stick profile."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def run_case(sapien, np, timestep, mass_scale, friction):
    from xbox_gamepad_physics.robotwin import load_into_scene

    scene = sapien.Scene([sapien.physx.PhysxCpuSystem()])
    scene.set_timestep(timestep)
    gamepad = load_into_scene(
        scene,
        pose=sapien.Pose(),
        fixed_root=True,
        profile="left_stick",
        attach_visual=False,
    )
    articulation = gamepad.articulation
    links = {link.name: link for link in articulation.get_links()}
    for name in ("left_stick_x_frame", "left_stick"):
        link = links[name]
        link.set_mass(link.get_mass() * mass_scale)
        link.set_inertia(np.asarray(link.get_inertia()) * mass_scale)

    physical_material = scene.create_physical_material(*friction)
    for link in articulation.get_links():
        for shape in link.get_collision_shapes():
            shape.set_physical_material(physical_material)

    gamepad.set_joint_positions({"left_stick_x": 0.2, "left_stick_y": -0.1})
    articulation.set_qvel(np.zeros(2))
    max_return_q = 0.0
    for _ in range(round(2.0 / timestep)):
        for link in articulation.get_links():
            link.wake_up()
        scene.step()
        q = np.asarray(articulation.get_qpos(), dtype=float)
        if not np.isfinite(q).all():
            raise RuntimeError("non-finite qpos during passive return")
        max_return_q = max(max_return_q, float(np.abs(q).max()))
    return_final = gamepad.joint_positions()

    gamepad.set_joint_positions({"left_stick_x": 0.0, "left_stick_y": 0.0})
    articulation.set_qvel(np.zeros(2))
    pivot = np.array([-0.038035359991741326, 0.024133629044164898, 0.01212386322086352])
    start = pivot + np.array([0.027, 0.0, 0.016])
    end = pivot + np.array([0.011, 0.0, 0.016])
    builder = scene.create_actor_builder()
    builder.add_sphere_collision(radius=0.006, material=physical_material)
    builder.set_initial_pose(sapien.Pose(start))
    pusher = builder.build_kinematic(name="left_stick_contact_probe")
    peak = 0.0
    steps = round(1.0 / timestep)
    contact_frames = 0
    for index in range(steps):
        alpha = index / (steps - 1)
        pusher.set_pose(sapien.Pose(start * (1.0 - alpha) + end * alpha))
        for link in articulation.get_links():
            link.wake_up()
        scene.step()
        q = np.asarray(articulation.get_qpos(), dtype=float)
        if not np.isfinite(q).all():
            raise RuntimeError("non-finite qpos during contact probe")
        peak = max(peak, abs(float(q[0])))
        contact_frames += bool(scene.get_contacts())
    pusher.set_pose(sapien.Pose(start))
    for _ in range(steps):
        for link in articulation.get_links():
            link.wake_up()
        scene.step()
    released = gamepad.joint_positions()
    passed = (
        abs(return_final["left_stick_x"]) < 1e-4
        and abs(return_final["left_stick_y"]) < 1e-4
        and 0.05 < peak <= math.radians(23.0) + 0.01
        and abs(released["left_stick_x"]) < 1e-4
        and abs(released["left_stick_y"]) < 1e-4
        and contact_frames > 0
    )
    return {
        "timestep_s": timestep,
        "mass_scale": mass_scale,
        "moving_mass_kg": 0.005 * mass_scale,
        "static_friction": friction[0],
        "dynamic_friction": friction[1],
        "restitution": friction[2],
        "max_return_abs_q_rad": max_return_q,
        "return_final_qpos": return_final,
        "contact_frames": contact_frames,
        "contact_peak_abs_q_rad": peak,
        "released_qpos": released,
        "passed": passed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import numpy as np
    import sapien

    cases = []
    for timestep in (1 / 120, 1 / 240, 1 / 480):
        for mass_scale in (0.4, 1.0, 2.0):
            for friction in ((0.2, 0.15, 0.0), (0.5, 0.4, 0.05), (0.8, 0.7, 0.15)):
                cases.append(run_case(sapien, np, timestep, mass_scale, friction))
    report = {
        "sapien": sapien.__version__,
        "profile": "left_stick",
        "case_count": len(cases),
        "passed": all(item["passed"] for item in cases),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case_count": len(cases), "passed": report["passed"]}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
