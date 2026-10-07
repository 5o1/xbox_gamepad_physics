"""Compiled-model handle bound exclusively through MuJoCo element names."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from xbox_gamepad_physics.errors import AssetImportError


@dataclass(frozen=True)
class MujocoGamepadHandle:
    """Named access to one compiled Xbox One S instance.

    Addresses into ``qpos``, ``qvel``, and sensor buffers are deliberately not
    cached here. MuJoCo's named model/data views resolve addresses from the
    compiled model, so attachment ordering and parent-model changes cannot
    silently invalidate hard-coded indices.
    """

    model: Any
    data: Any
    joint_names: Mapping[str, str]
    sensor_names: Mapping[str, str]
    _model_joints: Mapping[str, Any]
    _data_joints: Mapping[str, Any]
    _model_sensors: Mapping[str, Any]
    _data_sensors: Mapping[str, Any]

    def joint(self, logical_name: str) -> Any:
        """Return the compiled model's named joint view."""

        return _lookup_logical(self._model_joints, logical_name, "joint")

    def joint_data(self, logical_name: str) -> Any:
        """Return the runtime data's named joint view."""

        return _lookup_logical(self._data_joints, logical_name, "joint")

    def joint_qpos(self, logical_name: str) -> Any:
        """Return the named joint's qpos view without assuming an address."""

        view = self.joint_data(logical_name)
        if not hasattr(view, "qpos"):
            raise AssetImportError(
                f"MuJoCo named joint data for {logical_name!r} has no qpos view."
            )
        return view.qpos

    def joint_qvel(self, logical_name: str) -> Any:
        """Return the named joint's qvel view without assuming an address."""

        view = self.joint_data(logical_name)
        if not hasattr(view, "qvel"):
            raise AssetImportError(
                f"MuJoCo named joint data for {logical_name!r} has no qvel view."
            )
        return view.qvel

    def sensor(self, logical_name: str) -> Any:
        """Return the compiled model's named sensor view."""

        return _lookup_logical(self._model_sensors, logical_name, "sensor")

    def sensor_data(self, logical_name: str) -> Any:
        """Return the runtime data's named sensor view."""

        return _lookup_logical(self._data_sensors, logical_name, "sensor")

    def sensor_value(self, logical_name: str) -> Any:
        """Return the named sensor's data view."""

        view = self.sensor_data(logical_name)
        if not hasattr(view, "data"):
            raise AssetImportError(
                f"MuJoCo named sensor data for {logical_name!r} has no data view."
            )
        return view.data


def bind_handle(
    model: Any,
    data: Any,
    *,
    joints: Mapping[str, str],
    sensors: Mapping[str, str],
    prefix: str = "",
    suffix: str = "",
) -> MujocoGamepadHandle:
    """Bind a handle after compilation using declared element names only."""

    qualified_joints = {
        logical: f"{prefix}{local}{suffix}" for logical, local in joints.items()
    }
    qualified_sensors = {
        logical: f"{prefix}{local}{suffix}" for logical, local in sensors.items()
    }

    model_joints, data_joints = _bind_kind(
        model, data, "joint", qualified_joints
    )
    model_sensors, data_sensors = _bind_kind(
        model, data, "sensor", qualified_sensors
    )

    return MujocoGamepadHandle(
        model=model,
        data=data,
        joint_names=MappingProxyType(qualified_joints),
        sensor_names=MappingProxyType(qualified_sensors),
        _model_joints=MappingProxyType(model_joints),
        _data_joints=MappingProxyType(data_joints),
        _model_sensors=MappingProxyType(model_sensors),
        _data_sensors=MappingProxyType(data_sensors),
    )


def _bind_kind(
    model: Any, data: Any, kind: str, names: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not names:
        return {}, {}
    model_accessor = getattr(model, kind, None)
    data_accessor = getattr(data, kind, None)
    if not callable(model_accessor) or not callable(data_accessor):
        raise AssetImportError(
            f"Installed MuJoCo runtime lacks named {kind} access on model or data."
        )

    model_views: dict[str, Any] = {}
    data_views: dict[str, Any] = {}
    for logical, compiled_name in names.items():
        try:
            model_view = model_accessor(compiled_name)
            data_view = data_accessor(compiled_name)
        except Exception as exc:
            raise AssetImportError(
                f"Compiled MuJoCo model is missing {kind} {compiled_name!r} "
                f"required by logical binding {logical!r}."
            ) from exc
        if model_view is None or data_view is None:
            raise AssetImportError(
                f"Compiled MuJoCo model is missing {kind} {compiled_name!r} "
                f"required by logical binding {logical!r}."
            )
        model_views[logical] = model_view
        data_views[logical] = data_view
    return model_views, data_views


def _lookup_logical(values: Mapping[str, Any], name: str, kind: str) -> Any:
    try:
        return values[name]
    except KeyError as exc:
        available = ", ".join(sorted(values)) or "none"
        raise KeyError(
            f"Unknown logical {kind} {name!r}; available {kind}s: {available}."
        ) from exc
