"""Compare recorded non-visual full-control behavior across both backends."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROBOTWIN = ROOT / "build" / "experiments" / "robotwin_full_controls" / "result.json"
MUJOCO = ROOT / "build" / "experiments" / "mujoco_full_controls" / "result.json"
DEFAULT_OUTPUT = ROOT / "build" / "experiments" / "full_controls_backend_comparison.json"


def build() -> dict:
    robotwin = json.loads(ROBOTWIN.read_text())
    mujoco = json.loads(MUJOCO.read_text())
    channels = sorted(set(robotwin["endpoint_checks"]) | set(mujoco["endpoint_checks"]))
    endpoint_error = {
        channel: abs(
            robotwin["endpoint_checks"][channel]
            - mujoco["endpoint_checks"][channel]
        )
        for channel in channels
    }
    return {
        "schema_version": 1,
        "profile": "full_controls",
        "channels": channels,
        "endpoint_absolute_error": endpoint_error,
        "maximum_endpoint_absolute_error": max(endpoint_error.values()),
        "command_roundtrip_max_error": {
            "robotwin": robotwin["command_roundtrip_max_error"],
            "mujoco": mujoco["command_roundtrip_max_error"],
        },
        "pair_roundtrip_error": {
            "robotwin": robotwin["pair_roundtrip_error"],
            "mujoco": mujoco["pair_roundtrip_error"],
        },
        "passive_return_l1_ratio": {
            "robotwin": robotwin["return_final_l1"] / robotwin["return_initial_l1"],
            "mujoco": mujoco["return_final_l1"] / mujoco["return_initial_l1"],
        },
        "finite": robotwin["finite"] and mujoco["finite"],
        "scope": "Named endpoint/state mapping and passive-return summary; no visual or hardware acceptance.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
