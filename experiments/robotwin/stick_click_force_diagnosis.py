"""Bounded native-force diagnosis for the zero-motion T1 observation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from tests.acceptance.robotwin.stick_click import setup, shaft, sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    plan = {
        "question": "Does the exact T1 fixture receive a positive generalized click load from native world-space force on its loaded cap link?",
        "conditions": ["zero", "positive_each_step", "negative_each_step", "positive_first_step_only"],
        "force_n": 12., "steps_per_condition": 10, "dt_s": .004,
        "unchanged": "Same physical snapshot, 1 s settling, and tilt-only holding drives as T1; no click state or target writes.",
        "interpretation": "Positive-each-step should move q upward; negative should stay at the lower stop. First-step-only compares force clearing. If no identifiable harness bug is found, retain the failed T1 and stop.",
    }
    (args.output/"plan.json").write_text(json.dumps(plan, indent=2)+"\n")
    results = []
    for condition in plan["conditions"]:
        e = setup("left")
        joint = e.joints["left_stick_click"]
        cap = e.cap
        native_articulations = e.scene.get_all_articulations()
        metadata = {
            "condition": condition, "link": cap.name,
            "entity_name": cap.entity.name,
            "same_loaded_link": cap == next(l for l in e.art.get_links() if l.name == "left_stick"),
            "articulation_in_scene": e.art in native_articulations,
            "root_joint_type": e.art.root.joint.type,
            "click_parent": joint.get_parent_link().name,
            "click_child": joint.get_child_link().name,
            "limits_m": joint.get_limits().tolist(), "target_m": joint.get_drive_target().tolist(),
            "stiffness_n_per_m": joint.stiffness, "damping_ns_per_m": joint.damping,
            "effort_limit_n": joint.force_limit,
            "before": sample(e),
        }
        rows = []
        for step in range(plan["steps_per_condition"]):
            inward, center = shaft(e)
            sign = -1 if condition == "negative_each_step" else 1
            active = condition != "zero" and (condition != "positive_first_step_only" or step == 0)
            force = sign*12.*inward if active else np.zeros(3)
            frame = (joint.get_child_link().entity_pose*joint.get_pose_in_child()).to_transformation_matrix()
            axis = frame[:3, 0]
            before = sample(e)
            sleeping_before = cap.sleeping
            if active:
                cap.add_force_at_point(force, center, mode="force")
            sleeping_after_force = cap.sleeping
            e.scene.step()
            rows.append({"step": step, "before": before, "after": sample(e),
                "force_n_world": force.tolist(), "point_m_world": center.tolist(),
                "native_positive_click_axis_world": axis.tolist(),
                "generalized_click_force_projection_n": float(force @ axis),
                "sleeping_before": sleeping_before, "sleeping_after_force": sleeping_after_force,
                "sleeping_after_step": cap.sleeping,
                "qvel_m_s": e.gamepad.joint_velocity("left_stick_click")})
        results.append({**metadata, "steps": rows})
        (args.output/"results.json").write_text(json.dumps({"plan": plan, "results": results}, indent=2)+"\n")
    print(json.dumps([{ "condition": r["condition"],
        "q_m": [x["after"]["q_m"] for x in r["steps"]],
        "projection_n": r["steps"][0]["generalized_click_force_projection_n"],
        "same_link": r["same_loaded_link"], "in_scene": r["articulation_in_scene"]} for r in results]))


if __name__ == "__main__":
    main()
