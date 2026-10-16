"""Name-addressed facade for an Xbox One S SAPIEN articulation.

The public API deliberately accepts joint names.  SAPIEN's qpos ordering is an
implementation detail established when the URDF is loaded and must not leak
into callers or training code.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from .errors import JointConfigurationError, SceneCompatibilityError
from xbox_gamepad_physics.backends.common.handle import SignalHandleMixin, ResetRequest
from xbox_gamepad_physics.backends.common.model import Pose
from xbox_gamepad_physics.controller import GamepadSignalController
from xbox_gamepad_physics.state import GamepadState, XBOX_ONE_S_CHANNELS


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


class XboxOneSArticulation(SignalHandleMixin):
    """A name-addressed handle around the underlying SAPIEN articulation."""

    asset_id = "xbox_one_s"
    backend = "robotwin"
    profile = "full_controls"
    capabilities = frozenset({"named_joints", "signals", "birth_fixed_free", "runtime_root_switch_cpu"})

    def __init__(
        self,
        articulation: Any,
        expected_joint_names: Iterable[str],
        signal_controller: GamepadSignalController,
        *,
        scene: Any = None,
    ):
        self._articulation = articulation
        self._scene = scene
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
        if not isinstance(signal_controller, GamepadSignalController):
            raise TypeError("signal_controller must be a GamepadSignalController")
        self._signal_controller = signal_controller

    @property
    def articulation(self) -> Any:
        """Underlying SAPIEN object for scene-level operations."""

        return self._articulation

    @property
    def root_fixed(self) -> bool:
        """Whether the existing articulation root is fixed (read-only)."""
        kind = self._articulation.root.joint.type
        # SAPIEN 3.0.3 reads the free root's eUNDEFINED as "undefined";
        # its setter accepts "free". Keep the established setter spelling.
        if kind not in ("fixed", "free", "undefined"):
            raise SceneCompatibilityError(f"unsupported root joint type {kind!r}")
        return kind == "fixed"

    def set_root_fixed(self, fixed: bool) -> dict[str, Any] | None:
        """Fix/release this articulation between two completed ``scene.step()`` calls.

        CPU PhysX only; SAPIEN ``PhysxGpuSystem`` (including batched physics)
        raises SceneCompatibilityError before changing anything. GPU rendering
        with CPU physics is supported. Do not call concurrently with a step.

        Pose, joint positions/velocities and drive targets are retained. Fixing
        sets PhysX eFIX_BASE: the solver uses zero base velocity on the next
        step; the immediate velocity getter may still contain the old value.
        Releasing explicitly zeros root linear/angular velocity before waking
        the root. This preserves the existing teleop/replay operation order.

        Return None without writes/wake-up when already in the requested state.
        Otherwise return the legacy teleop record: from/to roles (moving/fixed),
        pre-switch pose [x,y,z,qw,qx,qy,qz], named joint_positions, drive_targets,
        and after-minus-before signal_delta for all canonical channels.
        See docs/robotwin_backend.md for upstream evidence and the known tilt
        stick deflection. ``fixed_root`` at load time remains the initial state.
        """
        if type(fixed) is not bool:
            raise TypeError("fixed must be bool")
        was_fixed = self.root_fixed
        if fixed == was_fixed:
            return None
        from sapien.physx import PhysxGpuSystem

        art = self._articulation
        scene = self._scene if self._scene is not None else art.root.entity.scene
        if isinstance(scene.physx_system, PhysxGpuSystem):
            raise SceneCompatibilityError(
                "set_root_fixed requires CPU PhysX; SAPIEN PhysxGpuSystem/batched "
                "GPU physics cannot use this root velocity/transition API"
            )
        before = self.gamepad_state()
        pose = art.get_root_pose()
        record = {
            "from": "fixed" if was_fixed else "moving",
            "to": "fixed" if fixed else "moving",
            "pose": [float(x) for x in (*pose.p, *pose.q)],
            "joint_positions": self.joint_positions(),
            "drive_targets": {
                j.name: float(j.get_drive_target()[0]) for j in art.get_active_joints()
            },
        }
        art.root.joint.type = "fixed" if fixed else "free"
        if self.root_fixed != fixed:
            raise SceneCompatibilityError("SAPIEN did not apply the requested root joint type")
        if not fixed:
            art.set_root_linear_velocity([0, 0, 0])
            art.set_root_angular_velocity([0, 0, 0])
        art.root.wake_up()
        after = self.gamepad_state()
        record["signal_delta"] = {
            n: after.channel(n) - before.channel(n) for n in XBOX_ONE_S_CHANNELS
        }
        return record

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


    def root_pose(self) -> Pose:
        pose = self._articulation.get_root_pose()
        return Pose(tuple(float(v) for v in pose.p), tuple(float(v) for v in pose.q))

    def root_twist(self):
        return (tuple(float(v) for v in self._articulation.get_root_linear_velocity()),
                tuple(float(v) for v in self._articulation.get_root_angular_velocity()))

    def restore_passive_targets(self) -> None:
        for name, value in self._passive_targets.items():
            self.set_joint_target(name, value)

    def reset(self, request: ResetRequest) -> None:
        """Apply an explicit state reset between caller-owned physics steps."""
        if request.targets not in ("passive", "preserve"):
            raise ValueError("reset targets must be passive or preserve")
        if request.root_pose is not None:
            from .loader import _coerce_pose
            pose = request.root_pose
            self._articulation.set_root_pose(_coerce_pose([*pose.position_m, *pose.orientation_wxyz]))
        if request.root_twist is not None:
            self._articulation.set_root_linear_velocity(request.root_twist[0])
            self._articulation.set_root_angular_velocity(request.root_twist[1])
        if request.joint_positions is not None:
            self.set_joint_positions(request.joint_positions)
        if request.joint_velocities is not None:
            qvel = self._articulation.get_qvel().copy()
            for name, value in request.joint_velocities.items():
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("joint velocities must be finite")
                qvel[self._binding(name).qpos_offset] = number
            self._articulation.set_qvel(qvel)
        if request.targets == "passive":
            self.restore_passive_targets()
