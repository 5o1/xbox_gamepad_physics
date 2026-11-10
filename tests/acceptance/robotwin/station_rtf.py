"""Run unchanged upstream protocols with station performance overrides.

No scoring expressions or protocol data are replaced. Screening uses the
existing T3v2 plus View/Menu/Guide T4 cases; full runs collect the whole suite.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

from experiments.robotwin.station_rtf.overrides import policy
from tests.acceptance.robotwin import (executor, run_suite, stick_click,
    stick_click_t3_point_v2, stick_cone_production)


def main():
    import sapien
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--iterations", nargs=2, type=int)
    p.add_argument("--sleep-threshold", type=float)
    p.add_argument("--batch-size", type=int)
    p.add_argument("--batch-library", type=Path)
    p.add_argument("--suite", choices=["t1", "screen", "full"], required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    resources = Path(os.environ["XBOX_GAMEPAD_PHYSICS_RESOURCES"])
    sapien.physx.set_scene_config(cpu_workers=0, enable_tgs=True)
    started = time.monotonic()
    summary = dict(suite=a.suite, iterations=a.iterations, sleep_threshold=a.sleep_threshold,
        versions={n: importlib.metadata.version(n) for n in ["sapien", "xbox-gamepad-physics"]},
        cpu_affinity=sorted(os.sched_getaffinity(0)), results={})

    def capture(name):
        path = a.output/name/"results.json"
        data = json.loads(path.read_text())
        rows = data["results"]
        passed = lambda r: bool(r.get("passed", r.get("status") == "passed"))
        summary["results"][name] = dict(passed=sum(passed(r) for r in rows),
            executed=sum(r.get("status") != "not_run" for r in rows),
            failed=[r for r in rows if not passed(r) and r.get("status") != "not_run"],
            passed_cases=[r.get("case", [r.get("side"), r.get("angle_deg", r.get("vertical_force_n", r.get("direction", r.get("multiplier"))))]) for r in rows if passed(r)],
            results_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        summary["elapsed_s"] = time.monotonic()-started
        (a.output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")

    with policy(a.iterations, a.sleep_threshold, a.batch_size, a.batch_library) as batch_records, \
         patch.object(executor, "create_scene", side_effect=run_suite.cpu_scene):
        summary["batch_records"] = batch_records
        if a.suite in ("t1", "full"):
            stick_click.t1(a.output/"T1", stop_on_failure=False)
            capture("T1")
        if a.suite == "full":
            stick_click.t2(a.output/"T2")
            capture("T2")
            stick_cone_production.run(a.output/"cone")
            capture("cone")
        if a.suite in ("screen", "full"):
            stick_click_t3_point_v2.run(resources, a.output/"T3v2", "new")
            capture("T3v2")
            run_suite.run(resources, a.output/"T4",
                cases=["View", "Menu", "Guide"] if a.suite == "screen" else None,
                collect_all=True)
            capture("T4")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
