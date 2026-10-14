"""Compatibility alias for the installed smoke implementation."""
import sys
from xbox_gamepad_physics.examples import smoke as _implementation
sys.modules[__name__] = _implementation
