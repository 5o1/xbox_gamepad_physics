"""Thin checkout alias for the installed viewer HTTP service."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from xbox_gamepad_physics.web.server import Handler, validate_asset_variant, validate_vendor, viewer_main
if __name__ == "__main__":
    raise SystemExit(viewer_main())
