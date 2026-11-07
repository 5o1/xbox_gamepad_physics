"""Review registered centering curves and residuals from native readbacks."""
import argparse
import json
import math
from pathlib import Path

from review_effort_probe import read, review


def run(root):
    result = review(root)
    protocol = read(root / "registration.json")["protocol"]
    conditions = {c["name"]: c for c in protocol["conditions"]}
    prior = read(root.parent / "full_model_effort_a1/independent_review.json")
    prior_by = {(r["side"], r["direction"]): r for r in prior["results"] if r["condition"] == "effort_7p4"}
    indexed = {(r["condition"], r["side"], r["direction"]): r for r in result["results"]}
    comparisons = []
    native_valid = True
    samples_checked = 0
    for row in result["results"]:
        folder = root / row["condition"] / (row["side"] + "_" + row["direction"])
        metadata = read(folder / "readback.json")
        for line in (folder / "state_trace.jsonl").read_text().splitlines():
            state = json.loads(line)
            before = state["step_diagnostics"]["before"]
            multiplier = conditions[row["condition"]]["center_multiplier"]
            q = list(before["pre_q_rad"].values())
            radius = math.hypot(*q)
            k = before["original_k_nm_per_rad"]
            theta = protocol["theta_max_rad"]
            if multiplier is None:
                expected = k
            else:
                epsilon = theta / multiplier
                expected = k * theta / (epsilon * math.tanh(multiplier)) if radius == 0 else (
                    k * theta * math.tanh(radius / epsilon) / (radius * math.tanh(multiplier)))
            native_valid &= math.isclose(before["K_eff_requested_nm_per_rad"], expected, rel_tol=1e-12)
            for stage in ("before", "after"):
                for name, actual in state["step_diagnostics"][stage]["native_drive_readback"].items():
                    original = metadata["after"]["joints"][name]
                    native_valid &= math.isclose(actual["stiffness"], expected, rel_tol=2e-7)
                    native_valid &= all(actual[key] == original[key] for key in (
                        "damping", "force_limit", "target", "friction", "friction_params"))
                    native_valid &= actual["mode"] == original["drive_mode"] == "force"
            samples_checked += 1
        if row["condition"] == "linear":
            a = row["release_max_deg"]
            b = prior_by[(row["side"], row["direction"])]["release_max_deg"]
            comparisons.append({"side": row["side"], "direction": row["direction"],
                                "linear_difference_deg": abs(a - b),
                                "linear_reproduced": abs(a - b) <= 0.05,
                                "center_5_ratio": indexed[("center_5", row["side"], row["direction"])]["release_max_deg"] / a,
                                "center_10_ratio": indexed[("center_10", row["side"], row["direction"])]["release_max_deg"] / a})
    result.update(native_curve_verified=bool(native_valid), native_samples_checked=samples_checked,
                  comparisons=comparisons,
                  mechanism_supported=len(comparisons) == 6 and all(
                      r["linear_reproduced"] and r["center_5_ratio"] < 0.5 and r["center_10_ratio"] < 0.5
                      for r in comparisons))
    result["evidence_valid"] &= native_valid and samples_checked == 18 * 750
    (root / "independent_review.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("results", "comparisons")}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    result = run(parser.parse_args().root)
    raise SystemExit(0 if result["evidence_valid"] else 1)
