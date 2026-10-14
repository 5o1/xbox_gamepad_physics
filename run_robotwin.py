#!/usr/bin/env python3
"""Thin checkout entry for the installed example runner."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from experiments import register_checkout_experiments
from xbox_gamepad_physics.examples.runner import main
if __name__ == "__main__":
    raise SystemExit(main())
