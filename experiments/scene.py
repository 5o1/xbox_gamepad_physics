"""Compatibility alias for the installed scene implementation."""
import sys
from xbox_gamepad_physics.examples import scene as _implementation
sys.modules[__name__] = _implementation
