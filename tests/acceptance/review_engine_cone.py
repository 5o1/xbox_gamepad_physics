"""Independently reconstruct the minimal two-hinge cone angle from native q."""
import argparse
import csv
import json
import math
from pathlib import Path


def review(folder):
    saved = json.loads((folder / "results.json").read_text())
    rows = []
    for case in saved["cases"]:
        side = case["side"]
        steady, angle_errors, click = [], [], []
        with Path(case["trace_path"]).open() as stream:
            for sample in csv.DictReader(stream):
                x = float(sample[f"q_{side}_stick_x"])
                y = float(sample[f"q_{side}_stick_y"])
                reconstructed = math.degrees(math.acos(max(-1.0, min(1.0, math.cos(x) * math.cos(y)))))
                angle_errors.append(abs(reconstructed - float(sample["shaft_angle_deg"])))
                time = float(sample["time_s"])
                if 0.8 - 1e-9 <= time <= 1.0 + 1e-9:
                    steady.append(reconstructed)
                    click.append(float(sample[f"q_{side}_stick_click"]))
        is_control = case["mechanism"] in ("stock_d6", "none")
        rows.append({"side": side, "mechanism": case["mechanism"],
                     "azimuth_deg": case["azimuth_deg"], "click_position_m": case["click_position_m"],
                     "preload_n": case["preload_n"], "steady_min_deg": min(steady),
                     "steady_max_deg": max(steady), "maximum_angle_record_error_deg": max(angle_errors),
                     "maximum_click_deviation_m": max(abs(q - case["click_position_m"]) for q in click),
                     "criterion_passed": min(steady) > 23.1 if is_control else (
                         min(steady) >= 22.9 and max(steady) <= 23.1)})
    by_mechanism = {}
    for row in rows:
        by_mechanism.setdefault(row["mechanism"], []).append(row)
    result = {"label": saved["label"], "cases": len(rows),
              "trace_geometry_consistent": max(r["maximum_angle_record_error_deg"] for r in rows) < 0.0001,
              "mechanisms": {name: {"cases": len(group), "criteria_passed": sum(r["criterion_passed"] for r in group),
                                     "steady_min_deg": min(r["steady_min_deg"] for r in group),
                                     "steady_max_deg": max(r["steady_max_deg"] for r in group)}
                             for name, group in by_mechanism.items()}, "results": rows}
    result["passed"] = result["trace_geometry_consistent"] and all(
        group["cases"] == group["criteria_passed"] == 64 for group in result["mechanisms"].values())
    (folder / "independent_review.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    result = review(parser.parse_args().folder)
    raise SystemExit(0 if result["passed"] else 1)
