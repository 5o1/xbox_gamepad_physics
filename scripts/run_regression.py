#!/usr/bin/env python3
"""Run the repository's checked-in unit tests without writing reports.

This command is deliberately a thin convenience wrapper. Test discovery and
reporting belong to unittest and Node; generated regression snapshots are not
part of the source tree's current-state contract.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> int:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profile",
        nargs="?",
        choices=("fast",),
        default="fast",
        help="run the local Python and JavaScript unit tests",
    )
    parser.parse_args()

    python_status = run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
            "-v",
        ]
    )
    if python_status:
        return python_status

    backend_status = run([sys.executable, "-m", "pytest", "tests/backends/mujoco", "-ra"])
    if backend_status:
        return backend_status

    javascript_tests = sorted(
        str(path.relative_to(ROOT)) for path in (ROOT / "tests").glob("test_*.mjs")
    )
    if not javascript_tests:
        print("No JavaScript unit tests found.", file=sys.stderr)
        return 1
    return run(["node", "--test", *javascript_tests])


if __name__ == "__main__":
    raise SystemExit(main())
