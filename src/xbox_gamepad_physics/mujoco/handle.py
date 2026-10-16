"""Native scalar handle; every binding uses a compiled MuJoCo name."""
from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any, Mapping

from xbox_gamepad_physics.backends.common.handle import ResetRequest, SignalHandleMixin
from xbox_gamepad_physics.backends.common.model import Pose
from xbox_gamepad_physics.errors import AssetImportError
from ._backend import require_mujoco


def _finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("joint values must be finite")
    return number


class MujocoGamepadHandle(SignalHandleMixin):
    """A handle belongs to one compiled model/data pair; rebind after compile.

    Position synchronization changes state and calls forward. Targets instead
    change named actuator controls, leaving the coordinates to native dynamics.
    Root mode is structural and must be chosen before compilation.
    """
    asset_id = "xbox_one_s"
    backend = "mujoco"
    capabilities = frozenset({"named_joints", "signals", "targets", "fixed_root", "free_root"})

    def __init__(self, model, data, *, joints, actuators, sensors, signal_controller,
                 profile="full_controls", root_body="controller_body", root_joint=None,
                 neutral_targets=None, initial_positions=None, findings=()):
        if getattr(data, "model", model) is not model:
            raise AssetImportError("MuJoCo data belongs to a different compiled model")
        self.model, self.data, self.profile = model, data, profile
        self.joint_bindings = MappingProxyType(dict(joints))
        self.actuator_names = MappingProxyType(dict(actuators))
        self.sensor_names = MappingProxyType(dict(sensors))
        self._model_joints, self._data_joints = _bind_kind(model, data, "joint", joints)
        self._model_sensors, self._data_sensors = _bind_kind(model, data, "sensor", sensors)
        self._model_actuators, self._data_actuators = _bind_kind(model, data, "actuator", actuators)
        if set(actuators) != set(joints):
            raise AssetImportError("Every control joint requires one named return actuator")
        for name, view in self._data_joints.items():
            if len(view.qpos) != 1 or len(view.qvel) != 1:
                raise AssetImportError(f"Control joint {name!r} must be scalar")
            actuator = self._model_actuators[name]
            if int(actuator.trnid[0]) != int(self._model_joints[name].id):
                raise AssetImportError(f"Actuator {actuators[name]!r} does not drive control {name!r}")
        self._signal_controller = signal_controller
        roots, roots_data = _bind_kind(model, data, "body", {"root": root_body})
        self._root_body, self._root_data = roots["root"], roots_data["root"]
        self._root_joint = None if root_joint is None else data.joint(root_joint)
        if neutral_targets is None or set(neutral_targets) != set(joints):
            raise AssetImportError("Manifest must provide evidenced neutral targets for every control joint")
        self._passive_targets = {name: _finite(value) for name, value in neutral_targets.items()}
        if initial_positions is None or set(initial_positions) != set(joints):
            raise AssetImportError("Manifest must provide common initial positions for every control joint")
        self._initial_positions = {name: _finite(value) for name, value in initial_positions.items()}
        self.findings = tuple(findings)

    @property
    def joint_names(self):
        return tuple(self.joint_bindings)

    @property
    def root_fixed(self):
        return self._root_joint is None

    def joint(self, name):
        return _lookup(self._model_joints, name, "joint")

    def joint_data(self, name):
        return _lookup(self._data_joints, name, "joint")

    def joint_qpos(self, name):
        return self.joint_data(name).qpos

    def joint_qvel(self, name):
        return self.joint_data(name).qvel

    def joint_position(self, name):
        return float(self.joint_qpos(name)[0])

    def joint_velocity(self, name):
        return float(self.joint_qvel(name)[0])

    def joint_positions(self):
        return {name: self.joint_position(name) for name in self.joint_names}

    def sensor(self, name):
        return _lookup(self._model_sensors, name, "sensor")

    def sensor_data(self, name):
        return _lookup(self._data_sensors, name, "sensor")

    def sensor_value(self, name):
        return self.sensor_data(name).data

    def set_joint_positions(self, positions: Mapping[str, float]):
        checked = [(self.joint_qpos(name), _finite(value)) for name, value in positions.items()]
        for view, value in checked:
            view[0] = value
        require_mujoco().mj_forward(self.model, self.data)

    def set_joint_target(self, name, target):
        actuator = _lookup(self._data_actuators, name, "actuator")
        actuator.ctrl[0] = _finite(target)

    def restore_passive_targets(self):
        for name, value in self._passive_targets.items():
            self.set_joint_target(name, value)

    def root_pose(self):
        return Pose(tuple(float(v) for v in self._root_data.xpos),
                    tuple(float(v) for v in self._root_data.xquat))

    def root_twist(self):
        import numpy as np
        mj = require_mujoco()
        velocity = np.empty(6)
        mj.mj_objectVelocity(self.model, self.data, mj.mjtObj.mjOBJ_BODY,
                             int(self._root_body.id), velocity, 0)
        return tuple(velocity[3:]), tuple(velocity[:3])

    def reset(self, request: ResetRequest):
        if request.targets not in {"passive", "preserve"}:
            raise ValueError("reset targets must be passive or preserve")
        if self.root_fixed and (request.root_pose is not None or request.root_twist is not None):
            raise ValueError("A fixed root pose/twist is structural; rebuild the spec to change it")
        if request.root_pose is not None:
            pose = request.root_pose
            if not isinstance(pose, Pose):
                raise TypeError("root_pose must be a common Pose")
            self._root_joint.qpos[:] = (*pose.position_m, *pose.orientation_wxyz)
        self.set_joint_positions(self._initial_positions if request.joint_positions is None
                                 else request.joint_positions)
        velocities = ({name: 0.0 for name in self.joint_names}
                      if request.joint_velocities is None else request.joint_velocities)
        checked = [(self.joint_qvel(n), _finite(v)) for n, v in velocities.items()]
        for view, value in checked:
            view[0] = value
        if request.root_twist is not None:
            import numpy as np
            linear, angular = request.root_twist
            linear = np.asarray([_finite(v) for v in linear])
            angular = np.asarray([_finite(v) for v in angular])
            if linear.shape != (3,) or angular.shape != (3,):
                raise ValueError("root_twist requires two triples")
            require_mujoco().mj_forward(self.model, self.data)
            self._root_joint.qvel[:3] = linear
            self._root_joint.qvel[3:] = self._root_data.xmat.reshape(3, 3).T @ angular
        if request.targets == "passive":
            self.restore_passive_targets()
        require_mujoco().mj_forward(self.model, self.data)


def bind_handle(model, data, *, joints, sensors=None, actuators=None, prefix="", suffix="",
                signal_controller=None, profile="full_controls", root_body="controller_body",
                root_joint=None, neutral_targets=None, initial_positions=None, findings=()):
    qualify = lambda names: {key: f"{prefix}{name}{suffix}" for key, name in names.items()}
    return MujocoGamepadHandle(
        model, data, joints=qualify(joints), sensors=qualify(sensors or {}),
        actuators=qualify(actuators or {}), signal_controller=signal_controller,
        profile=profile, root_body=f"{prefix}{root_body}{suffix}",
        root_joint=None if root_joint is None else f"{prefix}{root_joint}{suffix}",
        neutral_targets=neutral_targets, initial_positions=initial_positions, findings=findings)


def _bind_kind(model, data, kind, names):
    model_views, data_views = {}, {}
    for logical, name in names.items():
        try:
            model_views[logical] = getattr(model, kind)(name)
            data_views[logical] = getattr(data, kind)(name)
        except (KeyError, ValueError) as exc:
            raise AssetImportError(f"Compiled MuJoCo model is missing {kind} {name!r} for {logical!r}") from exc
    return model_views, data_views


def _lookup(values, name, kind):
    try:
        return values[name]
    except KeyError as exc:
        raise KeyError(f"Unknown logical {kind} {name!r}; available: {', '.join(values)}") from exc
