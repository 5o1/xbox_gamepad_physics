"""Lazy access to the optional MuJoCo Python bindings."""

from __future__ import annotations

import importlib
from types import ModuleType

from xbox_gamepad_physics.errors import MissingBackendDependencyError


def require_mujoco() -> ModuleType:
    """Return the optional :mod:`mujoco` module or raise a project error.

    Importing :mod:`xbox_gamepad_physics.mujoco` therefore does not require
    MuJoCo to be installed.  A backend dependency is required only when a
    model is loaded, attached, or compiled.
    """

    try:
        return importlib.import_module("mujoco")
    except (ImportError, ModuleNotFoundError) as exc:
        raise MissingBackendDependencyError(
            "MuJoCo runtime support requires the optional 'mujoco' Python "
            "package. Install the project's MuJoCo extra before loading an "
            "Xbox One S scene."
        ) from exc
