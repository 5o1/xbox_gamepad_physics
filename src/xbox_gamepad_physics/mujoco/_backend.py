"""Historical MuJoCo entry points: excluded from the v0.3 release scope."""

from __future__ import annotations

from typing import NoReturn

from xbox_gamepad_physics.errors import PhysicsNotReadyError


def reject_release_backend() -> NoReturn:
    raise PhysicsNotReadyError("MuJoCo is outside the v0.3 release scope")


def require_mujoco() -> NoReturn:
    reject_release_backend()
