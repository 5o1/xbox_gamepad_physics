"""Name-addressed facade for an Xbox One S SAPIEN articulation.

The public API deliberately accepts joint names.  SAPIEN's qpos ordering is an
implementation detail established when the URDF is loaded and must not leak
into callers or training code.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from .errors import JointConfigurationError
from xbox_gamepad_physics.state import GamepadState


def joint_name(joint: Any) -> str:
    """Return a SAPIEN joint name without importing SAPIEN."""

    getter = getattr(joint, "get_name", None)
    value = getter() if callable(getter) else getattr(joint, "name", None)
    if not isinstance(value, str) or not value:
        raise JointConfigurationError("an active joint has no non-empty name")
    return value


def joint_dof(joint: Any) -> int:
    """Return a joint's qpos width, rejecting an unverifiable value."""

    getter = getattr(joint, "get_dof", None)
    value = getter() if callable(getter) else getattr(joint, "dof", None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JointConfigurationError(
            f"active joint {joint_name(joint)!r} has invalid or unavailable DOF {value!r}"
        )
    return value


@dataclass(frozen=True)
class _JointBinding:
    name: str
    qpos_offset: int
    dof: int
    joint: Any


@dataclass(frozen=True)
class AxisMapping:
    channel: str
    joint: str
    lower: float
    upper: float


@dataclass(frozen=True)
class RadialGroup:
    channels: tuple[str, str]
    radius: float


class XboxOneSArticulation:
    """A name-addressed handle around the underlying SAPIEN articulation."""

    def __init__(
        self,
        articulation: Any,
        expected_joint_names: Iterable[str],
        axis_mappings: Iterable[AxisMapping] = (),
        radial_groups: Iterable[RadialGroup] = (),
    ):
        self._articulation = articulation
        get_active_joints = getattr(articulation, "get_active_joints", None)
        if not callable(get_active_joints):
            raise JointConfigurationError(
                "loaded object does not expose get_active_joints()"
            )

        bindings: dict[str, _JointBinding] = {}
        offset = 0
        for joint in get_active_joints():
            name = joint_name(joint)
            if name in bindings:
                raise JointConfigurationError(f"duplicate active joint name {name!r}")
            dof = joint_dof(joint)
            bindings[name] = _JointBinding(name, offset, dof, joint)
            offset += dof

        expected = tuple(expected_joint_names)
        if len(set(expected)) != len(expected):
            raise JointConfigurationError("profile contains duplicate joint names")
        missing = sorted(set(expected) - set(bindings))
        undeclared = sorted(set(bindings) - set(expected))
        if missing or undeclared:
            raise JointConfigurationError(
                "profile/articulation active-joint mismatch: "
                f"missing={missing}, undeclared={undeclared}"
            )
        non_scalar = sorted(name for name, value in bindings.items() if value.dof != 1)
        if non_scalar:
            raise JointConfigurationError(
                "Xbox One S controls require scalar active joints; "
                f"non-scalar={non_scalar}"
            )

        get_qpos = getattr(articulation, "get_qpos", None)
        if not callable(get_qpos):
            raise JointConfigurationError("loaded articulation does not expose get_qpos()")
        qpos = get_qpos()
        if len(qpos) != offset:
            raise JointConfigurationError(
                f"qpos length {len(qpos)} does not match active-joint DOF total {offset}"
            )
        self._bindings = bindings
        self._axis_mappings = tuple(axis_mappings)
        self._radial_groups = tuple(radial_groups)

    @property
    def articulation(self) -> Any:
        """Underlying SAPIEN object for scene-level operations."""

        return self._articulation

    @property
    def joint_names(self) -> tuple[str, ...]:
        """Names accepted by all position and target methods."""

        return tuple(self._bindings)

    def _binding(self, name: str) -> _JointBinding:
        try:
            return self._bindings[name]
        except KeyError as error:
            raise KeyError(
                f"unknown Xbox One S joint {name!r}; known={list(self._bindings)}"
            ) from error

    def joint_position(self, name: str) -> float:
        binding = self._binding(name)
        return float(self._articulation.get_qpos()[binding.qpos_offset])

    def joint_positions(self) -> dict[str, float]:
        qpos = self._articulation.get_qpos()
        return {
            name: float(qpos[binding.qpos_offset])
            for name, binding in self._bindings.items()
        }

    def joint_velocity(self, name: str) -> float:
        binding = self._binding(name)
        get_qvel = getattr(self._articulation, "get_qvel", None)
        if not callable(get_qvel):
            raise JointConfigurationError(
                "loaded articulation does not expose get_qvel()"
            )
        return float(get_qvel()[binding.qpos_offset])

    def set_joint_positions(self, positions: Mapping[str, float]) -> None:
        """Update selected qpos values by joint name in one articulation write."""

        checked: list[tuple[_JointBinding, float]] = []
        for name, value in positions.items():
            binding = self._binding(name)
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"joint position for {name!r} must be finite")
            checked.append((binding, number))

        qpos = self._articulation.get_qpos()
        copied = qpos.copy() if hasattr(qpos, "copy") else list(qpos)
        for binding, value in checked:
            copied[binding.qpos_offset] = value
        set_qpos = getattr(self._articulation, "set_qpos", None)
        if not callable(set_qpos):
            raise JointConfigurationError("loaded articulation does not expose set_qpos()")
        set_qpos(copied)

    def set_joint_target(self, name: str, target: float) -> None:
        number = float(target)
        if not math.isfinite(number):
            raise ValueError(f"joint target for {name!r} must be finite")
        setter = getattr(self._binding(name).joint, "set_drive_target", None)
        if not callable(setter):
            raise JointConfigurationError(
                f"joint {name!r} does not expose set_drive_target()"
            )
        setter(number)

    def gamepad_state(
        self, task_channels: Iterable[str] | None = None
    ) -> GamepadState:
        """Return the canonical tensor state exposed by this partial asset.

        Availability comes from the mappings actually present in the loaded
        simulator profile.  This prevents an unfinished physical asset from
        reporting unimplemented Xbox controls as valid neutral observations.
        """

        available_channels = tuple(mapping.channel for mapping in self._axis_mappings)
        values = {channel: 0.0 for channel in available_channels}
        for mapping in self._axis_mappings:
            q = self.joint_position(mapping.joint)
            scale = -mapping.lower if q < 0 else mapping.upper
            signal = q / scale
            values[mapping.channel] = max(-1.0, min(1.0, signal))
        for group in self._radial_groups:
            first, second = group.channels
            radius = math.hypot(values[first], values[second])
            if radius > group.radius:
                factor = group.radius / radius
                values[first] *= factor
                values[second] *= factor
        return GamepadState.xbox_one_s(
            values,
            available_channels=available_channels,
            task_channels=task_channels,
        )
