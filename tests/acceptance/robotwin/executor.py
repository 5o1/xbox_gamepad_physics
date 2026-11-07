"""Native SAPIEN execution of the unchanged frozen contact experiment."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import sapien

from tests.acceptance import load_suite, run_case
from tests.acceptance.records import ResultSink, summarize
from xbox_gamepad_physics.robotwin import create_scene, load_into_scene


class RobotwinPressExecutor:
    def setup(self, pose, dt=.004):
        previous = sapien.physx.get_scene_config()
        config = sapien.physx.get_scene_config()
        config.gravity = [0, 0, -9.81]
        sapien.physx.set_scene_config(config)
        try:
            self.scene = create_scene(timestep=dt, render=False)
        finally:
            sapien.physx.set_scene_config(previous)
        # Historical comparisons use immutable snapshots. Prepared DAG checks
        # exercise public resource resolution as well as the same native loader.
        snapshot = Path(os.environ["XBOX_GAMEPAD_PHYSICS_RESOURCES"]).resolve()
        if os.environ.get("XGP_ACCEPTANCE_PUBLIC_RESOURCES") == "1":
            self.gamepad = load_into_scene(self.scene, pose, fixed_root=True,
                                          attach_visual=False, collision="sdf")
        else:
            with patch("xbox_gamepad_physics.resources.resource_root", return_value=snapshot):
                self.gamepad = load_into_scene(self.scene, pose, fixed_root=True,
                                              attach_visual=False, collision="sdf")
        self.art = self.gamepad.articulation
        self.links = {link.name: link for link in self.art.get_links()}
        self.joints = {joint.name: joint for joint in self.art.get_active_joints()}
        self.dt = dt

    def add_ball(self, position, suite):
        builder = self.scene.create_actor_builder()
        material = suite.fixture["sphere_material"]
        builder.add_sphere_collision(radius=suite.settings["radius_m"], material=
            self.scene.create_physical_material(material["static_friction"], material["dynamic_friction"], material["restitution"]))
        mass, radius = suite.settings["mass_kg"], suite.settings["radius_m"]
        builder.set_mass_and_inertia(mass, sapien.Pose(), [2*mass*radius**2/5]*3)
        builder.set_initial_pose(sapien.Pose(position))
        entity = builder.build(name="test_ball")
        self.ball = entity.find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)
        mapping = suite.fixture["sapien_mapping"]
        for shape in self.ball.get_collision_shapes():
            shape.set_collision_groups(mapping["collision_groups"])
            shape.set_contact_offset(mapping["contact_offset_m"])
            shape.set_rest_offset(mapping["rest_offset_m"])

    def reset_case(self, suite, case):
        self.case = case
        self.setup([*case.root_pose.position_m, *case.root_pose.orientation_wxyz], suite.fixture["dt_s"])
        self.add_ball(np.asarray(case.plan["start_m"])-np.asarray(case.plan["direction"])*.015, suite)

    def ball_state(self):
        return {"position_m": self.ball.pose.p.tolist(), "velocity_m_s": self.ball.linear_velocity.tolist()}

    def apply_ball_force(self, force_n):
        self.ball.add_force_at_point(force_n, self.ball.pose.p)

    def step(self, dt_s):
        if dt_s != self.dt:
            raise ValueError("Frozen timestep mismatch")
        self.scene.step()

    def contacts(self):
        rows, internal = [], 0
        for contact in self.scene.get_contacts():
            bodies = [contact.bodies[0], contact.bodies[1]]
            names = [body.entity.name for body in bodies]
            if all(body in self.links.values() for body in bodies):
                internal += 1
            if "test_ball" in names:
                rows.append({"bodies": names, "points": [
                    {"position_m": p.position.tolist(), "normal": p.normal.tolist(),
                     "impulse_ns": p.impulse.tolist(), "separation_m": float(p.separation)}
                    for p in contact.points]})
        return rows, internal

    def sample(self):
        positions = self.gamepad.joint_positions()
        contacts, internal = self.contacts()
        return {"probe": {"pose": [float(x) for x in (*self.ball.pose.p, *self.ball.pose.q)],
                          "events": self.gamepad.physical_events()},
                "signals": self.gamepad.gamepad_state().as_dict(), "joints": positions,
                "contacts": contacts, "gamepad_internal_pairs": internal,
                "joint_limit_excess": {n: max(lo-positions[n], positions[n]-hi, 0.)
                    for n, (lo, hi) in self.case.joint_limits.items()
                    if not lo <= positions[n] <= hi}}


def execute_suite(output, *, case_ids=None, stop_on_regression=True):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    suite = load_suite()
    selected = set(case_ids) if case_ids is not None else {c.case_id for c in suite.cases}
    unknown = selected - {c.case_id for c in suite.cases}
    if unknown:
        raise ValueError(f"unknown frozen cases: {sorted(unknown)}")
    results = [{"case": c.case_id, "status": "not_run", "physics_passed": None,
                "baseline": dict(c.baseline), "regressed": None} for c in suite.cases]
    report = {"suite_id": suite.suite_id, "collision": "sdf", "results": results}
    def persist():
        report["summary"] = summarize(results)
        report["regressions"] = [r["case"] for r in results if r["regressed"]]
        (output/"results.json").write_text(json.dumps(report, indent=2)+"\n")
    persist()
    for i, case in enumerate(suite.cases):
        if case.case_id not in selected:
            continue
        sink = ResultSink(output/case.case_id/"trace.jsonl")
        executor = RobotwinPressExecutor()
        try:
            result = run_case(executor, suite, case, sink)
            results[i] = {**result, "status": "passed" if result["physics_passed"] else "failed",
                          "baseline": dict(case.baseline),
                          "regressed": bool(case.baseline["passed"] and not result["physics_passed"])}
        except Exception as exc:
            results[i].update(status="execution_error", missing_reason=f"{type(exc).__name__}: {exc}")
            persist()
            raise
        finally:
            sink.close()
        persist()
        if results[i]["regressed"] and stop_on_regression:
            break
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute_suite(args.output)
    print(json.dumps({"summary": result["summary"], "regressions": result["regressions"]}))
    raise SystemExit(bool(result["regressions"]))
