"""CPU-only T1/T2/cone/T3v2/T4 acceptance at 1 or 4 ms, using loader defaults.

Run from a checkout with its src directory on PYTHONPATH. Native scene and
iteration readbacks are archived for every case; there is no solver override.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import time
from unittest.mock import patch

from tests.acceptance.robotwin.timestep_protocol import TIMESTEPS, resample_suite, timing_table


def run(resources, output, timestep):
    import sapien
    from tests.acceptance.robotwin import (
        executor, run_suite, stick_click, stick_click_t3_point_v2, stick_cone_production)

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    resources = Path(resources).resolve()
    os.environ["XBOX_GAMEPAD_PHYSICS_RESOURCES"] = str(resources)
    # Exercise the public resource resolver and unmodified loader default path.
    os.environ["XGP_ACCEPTANCE_PUBLIC_RESOURCES"] = "1"
    sapien.physx.set_scene_config(cpu_workers=0, enable_tgs=True)
    suite = resample_suite(timestep)
    started = time.monotonic()
    summary = {
        "entrypoint": "tests.acceptance.robotwin.timestep_suite",
        "timestep_s": timestep, "timing": timing_table(timestep),
        "solver_override": None, "scene": "CPU-only, no renderer; TGS; cpu_workers=0",
        "versions": {name: importlib.metadata.version(name)
                     for name in ("sapien", "xbox-gamepad-physics")},
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "runtime_readbacks": [], "results": {},
        "protocol_sha256": {},
    }
    protocol_paths = (stick_click.PROTOCOL_PATH, stick_cone_production.P,
                      stick_click_t3_point_v2.P,
                      Path(__file__).resolve().parents[1] / "data/ruling20_sdf303_v1.json")
    for path in protocol_paths:
        summary["protocol_sha256"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    def persist():
        summary["elapsed_s"] = time.monotonic() - started
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    current = {"suite": None, "index": 0}
    original_setup = executor.RobotwinPressExecutor.setup

    def observed_setup(e, pose, dt=.004):
        original_setup(e, pose, dt)
        current["index"] += 1
        summary["runtime_readbacks"].append({
            "suite": current["suite"], "case_index": current["index"],
            "requested_timestep_s": dt, "actual_timestep_s": float(e.scene.get_timestep()),
            "art_iterations": [e.art.get_solver_position_iterations(),
                               e.art.get_solver_velocity_iterations()],
            "solver_policy": asdict(e.gamepad.solver_policy),
        })
        persist()

    def capture(name):
        path = output / name / "results.json"
        data = json.loads(path.read_text())
        rows = data["results"]
        passed = lambda row: bool(row.get("passed", row.get("status") == "passed"))
        case_id = lambda row: row.get("case", [row.get("side"), row.get(
            "angle_deg", row.get("multiplier", row.get("direction", row.get("vertical_force_n"))))])
        summary["results"][name] = {
            "passed": sum(passed(row) for row in rows),
            "executed": sum(row.get("status") != "not_run" for row in rows),
            "passed_cases": [case_id(row) for row in rows if passed(row)],
            "failed_cases": [case_id(row) for row in rows if not passed(row)],
            "results_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if name == "T4":
            baseline = {case.case_id for case in suite.cases if case.baseline["passed"]}
            summary["regressions"] = sorted(baseline - set(summary["results"][name]["passed_cases"]))
        persist()

    runs = (
        ("T1", lambda: stick_click.t1(output / "T1", stop_on_failure=False, timestep=timestep)),
        ("T2", lambda: stick_click.t2(output / "T2", timestep=timestep)),
        ("cone", lambda: stick_cone_production.run(output / "cone", timestep=timestep)),
        ("T3v2", lambda: stick_click_t3_point_v2.run(resources, output / "T3v2", "new", timestep=timestep)),
        ("T4", lambda: run_suite.run(resources, output / "T4", collect_all=True, suite=suite)),
    )
    with patch.object(executor, "create_scene", side_effect=run_suite.cpu_scene), \
         patch.object(executor.RobotwinPressExecutor, "setup", observed_setup):
        for name, action in runs:
            current.update(suite=name, index=0)
            action()
            capture(name)

    expected_iterations = [10, 1] if timestep == .001 else [64, 16]
    expected_passed = dict(T1=6, T2=12, cone=6, T3v2=10, T4=25 if timestep == .001 else 23)
    expected_executed = dict(T1=6, T2=12, cone=6, T3v2=10, T4=26)
    expected_failed_t4 = ["Pair"] if timestep == .001 else ["L3", "Pair", "R3"]
    summary["expected_passed"] = expected_passed
    summary["expected_iterations"] = expected_iterations
    summary["expected_failed_t4"] = expected_failed_t4
    summary["readbacks_match"] = len(summary["runtime_readbacks"]) == 60 and all(
        record["art_iterations"] == expected_iterations and
        record["solver_policy"]["source"] == "timestep_policy" and
        record["solver_policy"]["validated_timestep_s"] == timestep and math.isclose(
            record["actual_timestep_s"], timestep, rel_tol=1e-6, abs_tol=1e-10)
        for record in summary["runtime_readbacks"])
    summary["accepted"] = summary["readbacks_match"] and not summary["regressions"] and sorted(
        summary["results"]["T4"]["failed_cases"]) == expected_failed_t4 and all(
        result["passed"] == expected_passed[name] and result["executed"] == expected_executed[name]
        for name, result in summary["results"].items())
    persist()
    print(json.dumps(summary), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timestep", type=float, choices=TIMESTEPS, required=True)
    args = parser.parse_args()
    return int(not run(args.resources, args.output, args.timestep)["accepted"])


if __name__ == "__main__":
    raise SystemExit(main())
