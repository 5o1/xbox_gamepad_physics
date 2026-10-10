#!/usr/bin/env python3
"""Run a configured RoboTwin experiment from this checkout."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
try:
    import xbox_gamepad_physics
except ModuleNotFoundError as error:
    if error.name != "xbox_gamepad_physics":
        raise
    sys.path.insert(0, str(ROOT / "src"))

from experiments.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
