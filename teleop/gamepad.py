"""Compatibility entry for xbox_gamepad_physics.teleop.gamepad."""
import importlib
import runpy
import sys
if __name__ == "__main__":
    runpy.run_module("xbox_gamepad_physics.teleop.gamepad", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("xbox_gamepad_physics.teleop.gamepad")
