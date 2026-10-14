"""Compatibility wrapper for the packaged build_common_motion implementation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from xbox_gamepad_physics.builders import build_common_motion as _implementation

globals().update({name: value for name, value in vars(_implementation).items()
                  if not name.startswith("__")})
if __name__ == "__main__":
    _implementation.main()
