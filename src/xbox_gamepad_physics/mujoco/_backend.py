"""Lazy dependency boundary for the native MuJoCo backend."""

from __future__ import annotations

import importlib

from xbox_gamepad_physics.errors import MissingBackendDependencyError


def require_mujoco():
    """Import only when loading; M2 is validated against exactly 3.16.0."""
    try:
        module = importlib.import_module("mujoco")
    except ImportError as exc:
        raise MissingBackendDependencyError(
            "MuJoCo requires optional 'mujoco==3.16.0'."
        ) from exc
    if module.__version__ != "3.16.0":
        raise MissingBackendDependencyError(
            f"MuJoCo M2 requires 3.16.0; installed {module.__version__}."
        )
    return module
