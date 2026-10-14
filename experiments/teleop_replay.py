"""Compatibility alias for the packaged replay implementation."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("xbox_gamepad_physics.teleop.replay")
