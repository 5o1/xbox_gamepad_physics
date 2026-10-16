"""Run the frozen 26-case contact experiment without a renderer or GPU physics."""
from __future__ import annotations

import argparse

from xbox_gamepad_physics.mujoco.acceptance import execute_suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--case", action="append", dest="cases",
                        help="Restrict execution; every unrun frozen case remains null in results.json.")
    parser.add_argument('--physics-timestep', type=float,
                        help='Optional finer physical timestep for convergence; the frozen outer clock remains 0.004 s.')
    args = parser.parse_args()
    result = execute_suite(args.output, resource_root=args.resource_root, case_ids=args.cases,
                           physics_timestep_s=args.physics_timestep)
    print(result["summary"])
    print("Regressions against the frozen SAPIEN baseline:", result["regressions"])
    return int(bool(result["regressions"]))


if __name__ == "__main__":
    raise SystemExit(main())
