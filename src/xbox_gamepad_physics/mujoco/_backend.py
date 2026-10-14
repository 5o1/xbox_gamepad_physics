"""Historical MuJoCo entry points: excluded from the v0.3.0 release scope."""

from __future__ import annotations

from typing import NoReturn

from xbox_gamepad_physics.errors import PhysicsNotReadyError


def reject_release_backend() -> NoReturn:
    raise PhysicsNotReadyError("MuJoCo 不在 v0.3.0 发布范围内")


def require_mujoco() -> NoReturn:
    reject_release_backend()
