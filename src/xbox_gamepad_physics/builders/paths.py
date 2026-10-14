"""Read-only packaged evidence and caller-owned build paths."""
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[1] / "build_data"
# Convenience defaults for explicit maintainer script invocations in a checkout.
ROOT = Path.cwd()
