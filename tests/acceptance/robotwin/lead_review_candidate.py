"""Lead review: rescore saved candidate traces against the original criteria."""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

from tests.acceptance import load_suite, score_case


def read(path):
    return json.loads(path.read_text())


def trace(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def run(root):
    output = root / "frozen_acceptance"
    protocol = read(Path(__file__).with_name("stick_click_protocol.json"))
    t1 = []
    for side, angle in itertools.product(("left", "right"), protocol["T1"]["angles_deg"]):
        rows = trace(output / "T1" / f"{side}_{angle}" / "trace.jsonl")
        loading = [r for r in rows if r["loading"]]
        crossing = lambda level: next((r["applied_force_n"] for r in loading if r["signal"] >= level), None)
        f05, f50, f95 = [crossing(x) for x in (0.05, 0.5, 0.95)]
        width = f95 - f05 if f05 is not None and f95 is not None else None
        expected = 7.4 / math.cos(math.radians(angle))
        low = [r for r in rows if r["applied_force_n"] < 0.9 * 7.4 / r["cosine"]]
        low_max = max(max(r["signal"], r["raw_fraction"]) for r in low)
        error = max(abs(r["shaft_angle_deg"] - angle) for r in rows)
        passed = low_max <= 0.05 and width is not None and width <= 1 and f50 is not None and (
            abs(f50 / expected - 1) <= 0.1 and error <= 0.5
            and max(rows[-1]["signal"], rows[-1]["raw_fraction"]) <= 0.05)
        t1.append({"side": side, "angle_deg": angle, "trigger_n": f50, "width_n": width, "passed": passed})
    t2 = []
    for side, multiplier in itertools.product(("left", "right"), protocol["T2"]["force_multipliers"]):
        rows = trace(output / "T2" / f"{side}_{multiplier}" / "trace.jsonl")[-125:]
        value = (max(max(r["signal"], r["raw_fraction"]) for r in rows) if multiplier <= 0.95 else
                 min(min(r["signal"], r["raw_fraction"]) for r in rows))
        t2.append({"side": side, "multiplier": multiplier, "value": value,
                   "passed": value <= 0.05 if multiplier <= 0.95 else value >= 0.95})
    cone = []
    for side, direction in itertools.product(("left", "right"), ("diagonal45", "positive_x", "positive_y")):
        rows = trace(output / "cone" / f"{side}_{direction}" / "trace.jsonl")
        hold = [r for r in rows if 0.8 - 1e-9 <= r["time_s"] <= 1 + 1e-9]
        release = [r for r in rows if r["time_s"] >= 1.8 - 1e-9]
        lower, upper = min(r["angle_deg"] for r in hold), max(r["angle_deg"] for r in hold)
        residual = max(r["angle_deg"] for r in release)
        speed = max(abs(v) for r in release for v in r["tilt_qvel_rad_s"])
        control = trace(root / "cone_no_constraint_control" / f"{side}_{direction}" / "trace.jsonl")
        control_min = min(r["angle_deg"] for r in control if 0.8 - 1e-9 <= r["time_s"] <= 1 + 1e-9)
        lower_ok = control_min > 23.1 if direction == "diagonal45" else lower >= 22.9
        cone.append({"side": side, "direction": direction, "steady_min_deg": lower,
                     "steady_max_deg": upper, "return_max_deg": residual, "control_min_deg": control_min,
                     "passed": lower_ok and upper <= 23.1 and residual <= 0.1 and speed <= 0.01})
    t3 = []
    for side, force in itertools.product(("left", "right"), (1, 2, 4, 6, 8.14)):
        rows = trace(output / "T3" / f"{side}_{force}" / "trace.jsonl")
        hold = [r for r in rows if r["phase"] == "hold"]
        valid = min(r["angle_deg"] for r in hold) >= 1
        low_max = max(max(r["signal"], r["raw_fraction"]) for r in hold)
        positive_min = min(min(r["signal"], r["raw_fraction"]) for r in hold[-125:])
        passed = valid and (low_max <= 0.05 if force < 6.66 else positive_min >= 0.95) and rows[-1]["signal"] <= 0.05
        t3.append({"side": side, "force_n": force, "valid": valid, "hold_max": low_max,
                   "positive_min": positive_min if force == 8.14 else None, "passed": passed})
    suite = load_suite()
    t4 = {}
    for label in ("T4_candidate64", "T4_default10"):
        results = []
        for case in suite.cases:
            data = trace(output / label / case.case_id / "trace.jsonl")
            scored = score_case(suite, case, data)
            results.append({"case": case.case_id, "passed": scored["physics_passed"],
                            "target_min": scored["target_min"], "baseline_passed": case.baseline["passed"],
                            "regressed": case.baseline["passed"] and not scored["physics_passed"]})
        t4[label] = {"completed": len(results), "passed_cases": sum(r["passed"] for r in results),
                     "failures": [r["case"] for r in results if not r["passed"]],
                     "regressions": [r["case"] for r in results if r["regressed"]], "results": results}
    config_hash = hashlib.sha256((root / "CANDIDATE_CALIBRATION.json").read_bytes()).hexdigest()
    result = {"config_sha256": config_hash,
              "matches_frozen_config": config_hash == (root / "FROZEN_CONFIG_SHA256.txt").read_text().split()[0],
              "T1": t1, "T2": t2, "cone_written_criteria": cone, "T3": t3, "T4": t4}
    result["target_criteria_passed"] = result["matches_frozen_config"] and all(
        r["passed"] for group in (t1, t2, cone, t3) for r in group) and not t4["T4_candidate64"]["regressions"]
    (root / "LEAD_INDEPENDENT_REVIEW.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"target_criteria_passed": result["target_criteria_passed"],
                      "config_matches_frozen": result["matches_frozen_config"],
                      "T1": sum(r["passed"] for r in t1), "T2": sum(r["passed"] for r in t2),
                      "cone": sum(r["passed"] for r in cone), "T3": sum(r["passed"] for r in t3),
                      "T4": {k: {n: v for n, v in value.items() if n != "results"} for k, value in t4.items()}}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    result = run(parser.parse_args().root)
    raise SystemExit(0 if result["target_criteria_passed"] else 1)
