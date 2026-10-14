"""Compatibility alias for the installed runner implementation."""
import sys
from xbox_gamepad_physics.examples import runner as _implementation
sys.modules[__name__] = _implementation
