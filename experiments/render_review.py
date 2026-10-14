"""Compatibility alias for the installed render_review implementation."""
import sys
from xbox_gamepad_physics.examples import render_review as _implementation
sys.modules[__name__] = _implementation
