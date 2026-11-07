"""Recompute the full-model effort probe's outcomes from its recorded traces."""
import argparse
import copy
import itertools
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def review(root):
    registration = read(root / "registration.json")
    protocol = registration["protocol"]
    scoring = registration["cone_protocol"]["criteria"]
    rows = []
    for condition, side, direction in itertools.product(
        protocol["conditions"], protocol["sides"], protocol["directions"]
    ):
        folder = root / condition["name"] / (side + "_" + direction)
        states = [json.loads(line) for line in (folder / "state_trace.jsonl").read_text().splitlines()]
        cone = [json.loads(line) for line in (folder / "trace.jsonl").read_text().splitlines()]
        metadata = read(folder / "readback.json")
        hold = [r for r in cone if 0.8 - 1e-9 <= r["time_s"] <= 1 + 1e-9]
        release = [r for r in cone if r["time_s"] >= 1.8 - 1e-9]
        lower = min(r["angle_deg"] for r in hold)
        upper = max(r["angle_deg"] for r in hold)
        residual = max(r["angle_deg"] for r in release)
        speed = max(abs(v) for r in release for v in r["tilt_qvel_rad_s"])
        before, after = copy.deepcopy(metadata["before"]), copy.deepcopy(metadata["after"])
        friction_readback = True
        for suffix in ("x", "y"):
            name = side + "_stick_" + suffix
            actual = after["joints"][name]
            friction_readback &= abs(actual["friction"] - condition["legacy_coefficient"]) < 1e-7
            friction_readback &= all(abs(x - y) < 1e-9 for x, y in zip(
                actual["friction_params"], condition["friction_params"]))
            for key in ("friction", "friction_params"):
                before["joints"][name].pop(key)
                actual.pop(key)
        offset = metadata["qf_offsets"][side + "_stick_click"]
        preload_readback = abs(after["qf"][offset] - condition["click_qf_n"]) < 1e-6
        before["qf"][offset] = after["qf"][offset]
        qf = metadata["after"]["qf"]
        rows.append({
            "condition": condition["name"], "side": side, "direction": direction,
            "load_peak_deg": max(r["angle_deg"] for r in cone[:250]),
            "steady_min_deg": lower, "steady_max_deg": upper,
            "release_max_deg": residual, "release_max_speed_rad_s": speed,
            "cone_return_passed": lower >= scoring["single_axis_min_deg"]
            and upper <= scoring["single_axis_max_deg"]
            and residual <= scoring["release_max_deg"]
            and speed <= scoring["release_joint_speed_max_rad_s"],
            "load_max_click_fraction": max(r["click"][side]["raw_fraction"] for r in states[250:500]),
            "trace_consistent": len(states) == 750 and len(cone) == 500 and all(
                abs(s["total_angle_deg"] - c["angle_deg"]) < 1e-10
                for s, c in zip(states[250:], cone)),
            "only_registered_fields_changed": before == after,
            "friction_readback": bool(friction_readback), "preload_readback": preload_readback,
            "qf_persisted": all(r["qf"] == qf for r in states),
            "production_tgs": metadata["scene_config"]["enable_tgs"] is True,
        })
    by_key = {(r["condition"], r["side"], r["direction"]): r for r in rows}
    names = {c["name"] for c in protocol["conditions"]}
    h1 = None
    if {"legacy_7p4", "effort_7p4", "zero_7p4"} <= names:
        h1 = all(by_key[("legacy_7p4", s, d)]["load_peak_deg"] < 1
                 and by_key[("effort_7p4", s, d)]["load_peak_deg"] >= 1
                 and by_key[("zero_7p4", s, d)]["load_peak_deg"] >= 1
                 for s, d in itertools.product(protocol["sides"], protocol["directions"]))
    keys = ("trace_consistent", "only_registered_fields_changed", "friction_readback",
            "preload_readback", "qf_persisted", "production_tgs")
    result = {"completed_cases": len(rows), "evidence_valid": len(rows) == protocol["planned_cases"]
              and all(all(r[k] for k in keys) for r in rows),
              "H1_supported": h1, "cone_return_passed": sum(r["cone_return_passed"] for r in rows),
              "results": rows}
    (root / "independent_review.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    result = review(parser.parse_args().root)
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, indent=2))
    raise SystemExit(0 if result["evidence_valid"] else 1)
