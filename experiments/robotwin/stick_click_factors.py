"""Preregistered, one-factor click diagnostics for owner ruling 3."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from tests.acceptance.records import ResultSink
from tests.acceptance.robotwin.stick_click import setup, shaft, sample, save

PROTOCOL = Path(__file__).with_name("stick_click_factor_protocol.json")


from experiments.robotwin.joint_readback import policy


def run(output, new_resources, main_resources):
    p = json.loads(PROTOCOL.read_text())
    output.mkdir(parents=True, exist_ok=True)
    save(output/"registration.json", {"sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(), "protocol": p})
    results = []
    for condition in p["conditions"]:
        resources = new_resources if condition["model"] == "new" else main_resources
        os.environ["XBOX_GAMEPAD_PHYSICS_RESOURCES"] = str(resources.resolve())
        e = setup(p["side"], p["tilt_angle_deg"])
        before = policy(e)
        click_name = p["side"]+"_stick_click"
        click = e.joints[click_name]
        override = condition["override"] or {}
        if "friction" in override:
            click.set_friction(override["friction"])
        if "max_velocity" in override:
            click.set_max_velocity(override["max_velocity"])
        after = policy(e)
        differences = [{"joint": name, "field": field, "before": before[name][field], "after": value}
            for name, fields in after.items() for field, value in fields.items() if before[name][field] != value]
        folder = output/condition["name"]
        folder.mkdir(parents=True, exist_ok=True)
        metadata = {"condition": condition, "resource_root": str(resources.resolve()),
            "policy_before": before, "policy_after": after, "policy_differences": differences,
            "force_link": e.cap.name, "force_link_in_loaded_articulation": e.cap in e.art.get_links(),
            "native_articulation_in_scene": e.art in e.scene.get_all_articulations(),
            "physics_system": type(e.scene.physx_system).__name__, "actual_dt_s": e.scene.get_timestep()}
        save(folder/"readback.json", metadata)
        sink = ResultSink(folder/"trace.jsonl")
        rows = []
        try:
            count = round(p["ramp_up_s"]/p["dt_s"])
            for i in range(count+1):
                force_n = p["peak_force_n"]*i/count
                inward, center = shaft(e)
                vector = force_n*inward
                axis = (click.get_child_link().entity_pose*click.get_pose_in_child()).to_transformation_matrix()[:3, 0]
                e.cap.add_force_at_point(vector, center, mode="force")
                e.scene.step()
                row = {**sample(e), "step": i, "time_s": (i+1)*p["dt_s"],
                    "applied_force_n": force_n, "force_world_n": vector.tolist(),
                    "application_world_m": center.tolist(), "click_positive_axis_world": axis.tolist(),
                    "click_force_projection_n": float(vector @ axis),
                    "click_qvel_m_s": e.gamepad.joint_velocity(click_name)}
                sink.write(row)
                rows.append(row)
        finally:
            sink.close()
        crossing = lambda level: next((r["applied_force_n"] for r in rows if r["raw_fraction"] >= level), None)
        result = {"condition": condition["name"], "model": condition["model"],
            "before_click_policy": before[click_name], "after_click_policy": after[click_name],
            "policy_differences": differences, "steps": len(rows),
            "max_q_m": max(r["q_m"] for r in rows), "final_q_m": rows[-1]["q_m"],
            "max_raw_fraction": max(r["raw_fraction"] for r in rows),
            "first_05_force_n": crossing(.05), "first_50_force_n": crossing(.5),
            "first_95_force_n": crossing(.95),
            "max_abs_qvel_m_s": max(abs(r["click_qvel_m_s"]) for r in rows)}
        results.append(result)
        save(output/"results.json", {"protocol_id": p["protocol_id"], "results": results})
        print(json.dumps(result), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--new-resources", type=Path, required=True)
    parser.add_argument("--main-resources", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.new_resources, args.main_resources)
