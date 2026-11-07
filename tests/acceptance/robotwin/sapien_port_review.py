"""Independently score the phase-one SAPIEN port's recorded physical results.

Run the original port fixtures first. This audit reads measurements rather than
trusting their saved pass flags. It does not select production friction values.
"""
import argparse
import itertools
import json
import math
from pathlib import Path


def load(path):
    return json.loads(path.read_text())


def score_cpu(data):
    rows = data["onset"]
    expected = set(itertools.product(("legacy", "new"), (0.0, 2.0, 7.4), (-1, 1), range(3)))
    actual = [(r["mode"], r["preload_N"], r["direction"], r["repeat"]) for r in rows]
    checks = {"complete_onset_matrix": len(actual) == 36 and set(actual) == expected}
    new = [r["threshold_Nm"] for r in rows if r["mode"] == "new"]
    checks["new_threshold_within_5_percent"] = len(new) == 18 and all(
        v is not None and abs(v / 0.002 - 1) < 0.05 for v in new
    )
    checks["preload_spread_under_5_percent"] = bool(new) and all(v is not None for v in new) and (
        (max(new) - min(new)) / (sum(new) / len(new)) < 0.05
    )
    legacy = [[r["threshold_Nm"] for r in rows if r["mode"] == "legacy" and r["preload_N"] == p]
              for p in (0.0, 2.0, 7.4)]
    checks["legacy_preload_coupling_reproduced"] = all(
        len(group) == 6 and all(v is not None for v in group) for group in legacy
    ) and max(legacy[0]) < min(legacy[1]) and max(legacy[1]) < min(legacy[2])
    checks["onset_displacement_and_velocity"] = all(
        r["threshold_Nm"] is not None and r["direction"] * r["q_rad"] > 1e-5
        and r["direction"] * r["v_rad_s"] > 1e-4 for r in rows
    )
    dimensions = data["dimensions"]
    matrix = [(r["dt_s"], r["dynamic_Nm"], r["viscous_Nm_s_rad"], r["velocity_rad_s"])
              for r in dimensions]
    expected_dimensions = {(dt, dynamic, viscous, velocity)
                           for dt, (dynamic, viscous), velocity in itertools.product(
                               (0.0005, 0.00025), ((0.001, 0), (0, 0.0004), (0.001, 0.0004)),
                               (-2.0, -1.0, 1.0, 2.0))}
    checks["complete_dimension_matrix"] = len(matrix) == 24 and set(matrix) == expected_dimensions
    errors = []
    for r in dimensions:
        expected_effort = math.copysign(r["dynamic_Nm"], r["velocity_rad_s"]) + (
            r["viscous_Nm_s_rad"] * r["velocity_rad_s"])
        errors.append(abs((r["measured_Nm"] - expected_effort) / expected_effort))
    checks["dimension_error_under_5_percent"] = len(errors) == 24 and max(errors) < 0.05
    lifetime = data["lifetime"]
    parameter_rows = [r for r in lifetime if "params" in r]
    checks["lifecycle_parameters"] = {r["operation"] for r in parameter_rows} == {
        "initial", "remove_add_scene", "clone", "reparent_subtree"
    } and len(parameter_rows) == 4 and all(
        len(r["params"]) == 3 and all(abs(x - y) < 1e-9 for x, y in zip(r["params"], (0.002, 0.001, 0.0004)))
        and abs(r["legacy"] - 0.1) < 1e-7 for r in parameter_rows
    )
    brake = [r for r in lifetime if r["operation"] == "remounted_brake"]
    checks["remounted_brake"] = len(brake) == 2 and {r["torque_Nm"] for r in brake} == {0.0018, 0.0022} and all(
        (abs(r["q_rad"]) > 1e-5 and abs(r["v_rad_s"]) > 1e-4) == (r["torque_Nm"] > 0.002)
        for r in brake
    )
    return {"checks": checks, "new_thresholds_Nm": sorted(set(new)),
            "legacy_thresholds_Nm": [sorted(set(group)) for group in legacy],
            "maximum_dimension_relative_error": max(errors), "passed": all(checks.values())}


def score_reset(candidate, baseline):
    finite = lambda values: all(math.isfinite(x) for x in values)
    cameras = candidate["observation_camera_images"]
    qpos_diff = max(abs(x - y) for x, y in zip(candidate["robot_qpos"], baseline["robot_qpos"]))
    checks = {
        "candidate_version": candidate["sapien_version"] == "3.0.3+concon.physx5.6.1.a1",
        "new_api": candidate["has_new_friction_api"] is True,
        "same_task_seed": (candidate["task"], candidate["seed"]) == (baseline["task"], baseline["seed"]),
        "same_actor_count": candidate["actor_count"] == baseline["actor_count"] == 5,
        "robot_state": len(candidate["robot_qpos"]) == len(baseline["robot_qpos"]) == 38 and finite(candidate["robot_qpos"]),
        "four_valid_rgb_cameras": set(cameras) == set(baseline["observation_camera_images"]) and len(cameras) == 4 and all(
            r["shape"] == [240, 320, 3] and r["dtype"] == "uint8" and 0 <= r["min"] <= r["max"] <= 255
            for r in cameras.values()),
        "same_action_vector": candidate["joint_action_vector"] == baseline["joint_action_vector"],
        "pinned_render_device": candidate["render_device_pci"] == baseline["render_device_pci"] and candidate["cuda_visible_devices"] == "3",
        "finite_block_positions": all(finite(candidate[k]) for k in ("block1_pose", "block2_pose")),
    }
    return {"checks": checks, "maximum_robot_qpos_difference": qpos_diff,
            "maximum_block_position_difference_m": max(abs(x - y) for k in ("block1_pose", "block2_pose")
                                                       for x, y in zip(candidate[k], baseline[k])),
            "passed": all(checks.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    result = {"cpu": score_cpu(load(args.run / "cpu/results.json"))}
    baseline_rows = load(args.evidence / "baseline-pgs/results.json")["onset"]
    baseline_thresholds = {(r["preload_N"], r["direction"], r["repeat"]): r["threshold_Nm"]
                           for r in baseline_rows}
    candidate_rows = load(args.run / "cpu/results.json")["onset"]
    candidate_thresholds = {(r["preload_N"], r["direction"], r["repeat"]): r["threshold_Nm"]
                            for r in candidate_rows if r["mode"] == "legacy"}
    result["legacy_baseline"] = {"passed": len(baseline_thresholds) == 18 and candidate_thresholds == baseline_thresholds,
                                 "source": "baseline-pgs/results.json"}
    xbox = load(args.run / "xbox.json")
    result["xbox"] = {"passed": xbox["joints"] == 20 and xbox["finite"] is True and xbox["roundtrip_ok"] is True,
                      "scope": "SDF load, twenty CPU steps, public signal round trip; no contact acceptance"}
    result["reset"] = score_reset(load(args.run / "remote/reset.json"), load(args.evidence / "robotwin/baseline303.json"))
    gpu = load(args.run / "remote/gpu.json")
    result["gpu"] = {"passed": gpu["sapien_version"] == "3.0.3+concon.physx5.6.1.a1"
                     and gpu["cuda_visible_devices"] == "3"
                     and gpu["device_pci"] == load(args.run / "remote/reset.json")["render_device_pci"]
                     and gpu["step_count"] == len(gpu["qpos_after_steps"]) == len(gpu["qvel_after_steps"]) == 20
                     and abs(gpu["qpos_written_and_read_back"] - 0.123) < 1e-6
                     and all(math.isfinite(x) for x in gpu["qpos_after_steps"] + gpu["qvel_after_steps"])
                     and gpu["qpos_after_steps"][-1] > 0.12301 and gpu["qvel_after_steps"][-1] > 0,
                     "scope": "runtime, init, DLPack, DirectGPUAPI state and force; no GPU friction scan"}
    result["installed_wheel"] = {"passed": load(args.run / "installed_wheel_audit.json")["all_match"]}
    package = load(args.run / "source-and-package-audit.json")
    result["source_and_package"] = {"passed": package["all_source_files_match"]
                                   and not package["wheel_record_failures"]}
    points = load(args.run / "solver-comparison.json")
    point_matrix = {(r["tgs"], r["preload_N"], r["effort_Nm"]) for r in points}
    expected_points = set(itertools.product((False, True), (0.0, 2.0, 7.4), (0.0018, 0.0022)))
    result["solver_points"] = {"passed": len(points) == 12 and point_matrix == expected_points and all(
        (abs(r["displacement_rad"]) > 1e-5 and abs(r["velocity_rad_s"]) > 1e-4) == (r["effort_Nm"] > 0.002)
        for r in points), "scope": "twelve PGS/TGS points; no full TGS onset or contact scan"}
    result["passed"] = all(v["passed"] for v in result.values())
    (args.run / "review-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
