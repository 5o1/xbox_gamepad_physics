"""Read and validate the MuJoCo-specific part of a backend profile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from xbox_gamepad_physics.controller import (
    AxisSignalMapping,
    GamepadSignalController,
    PhysicalEventMapping,
    RadialSignalGroup,
    RadialSourceGroup,
    ScalarSignalMapping,
    SplitSignalMapping,
)
from xbox_gamepad_physics.errors import AssetImportError, MissingResourceError
from xbox_gamepad_physics.motion import load_motion_contract
from xbox_gamepad_physics.profiles import require_physics_ready
from xbox_gamepad_physics.resources import load_json_resource, resource_path


@dataclass(frozen=True)
class RuntimeManifest:
    """Validated MuJoCo runtime metadata from a ready backend profile."""

    profile: str
    entrypoint: str
    scenes: Mapping[str, str]
    joints: Mapping[str, str]
    sensors: Mapping[str, str]
    signal_controller: GamepadSignalController | None = None


def load_runtime_manifest(profile: str) -> RuntimeManifest:
    """Load a ready MuJoCo profile and its named runtime bindings.

    ``require_physics_ready`` enforces the repository-wide readiness gate.
    The checked-in placeholder profile intentionally fails here until the
    physical MJCF/MJZ resources have been generated and validated.
    """

    checked = require_physics_ready("mujoco", profile)
    raw = load_json_resource("mujoco", profile)

    backend = raw.get("backend")
    if backend != "mujoco":
        raise AssetImportError(
            f"MuJoCo profile {profile!r} declares backend {backend!r}; "
            "expected 'mujoco'."
        )

    entrypoint = _relative_resource_name(
        getattr(checked, "entrypoint", None),
        field="entrypoint",
        profile=profile,
    )
    scenes = _string_mapping(raw.get("scenes", {}), "scenes", profile)

    bindings = raw.get("bindings")
    if not isinstance(bindings, Mapping):
        raise AssetImportError(
            f"MuJoCo profile {profile!r} is ready but has no 'bindings' "
            "object. Compiled handles must bind joints and sensors by name."
        )
    joints = _string_mapping(bindings.get("joints", {}), "bindings.joints", profile)
    sensors = _string_mapping(
        bindings.get("sensors", {}), "bindings.sensors", profile
    )
    if not joints and not sensors:
        raise AssetImportError(
            f"MuJoCo profile {profile!r} has no named joint or sensor bindings."
        )

    motion_reference = raw.get("motion_contract")
    if motion_reference is not None:
        expected = f"common/xbox_one_s/motion/{profile}.json"
        if motion_reference != expected:
            raise AssetImportError(
                f"MuJoCo profile {profile!r} motion_contract must be {expected!r}."
            )
        motion = load_motion_contract(profile)
        if set(motion.joint_by_name) != set(joints):
            raise AssetImportError(
                f"MuJoCo profile {profile!r} bindings do not match common motion joints."
            )
        signal_controller = motion.signal_controller
    else:
        try:
            signal_controller = _signal_controller(raw.get("state_mapping"), set(joints))
        except (TypeError, ValueError) as exc:
            raise AssetImportError(
                f"MuJoCo profile {profile!r} has invalid state_mapping: {exc}"
            ) from exc

    return RuntimeManifest(
        profile=profile,
        entrypoint=entrypoint,
        scenes=MappingProxyType(dict(scenes)),
        joints=MappingProxyType(dict(joints)),
        sensors=MappingProxyType(dict(sensors)),
        signal_controller=signal_controller,
    )


def _signal_controller(value: Any, joints: set[str]) -> GamepadSignalController:
    if not isinstance(value, Mapping):
        raise TypeError("state_mapping must be an object")

    def records(field: str) -> list[Mapping[str, Any]]:
        raw = value.get(field, [])
        if not isinstance(raw, list) or any(
            not isinstance(item, Mapping) for item in raw
        ):
            raise TypeError(f"state_mapping.{field} must be a list of objects")
        return raw

    def source(item: Mapping[str, Any]) -> str:
        name = item.get("joint")
        if not isinstance(name, str) or name not in joints:
            raise ValueError(f"unknown mapped joint {name!r}")
        return name

    def number(item: Mapping[str, Any], field: str) -> float:
        raw = item.get(field)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError(f"{field} must be numeric")
        return float(raw)

    def neutral_epsilon(item: Mapping[str, Any]) -> float:
        raw = item.get("neutral_epsilon", 0.0)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError("neutral_epsilon must be numeric")
        return float(raw)

    axes = tuple(
        AxisSignalMapping(
            str(item.get("channel")),
            source(item),
            number(item, "lower"),
            number(item, "upper"),
        )
        for item in records("axes")
    )
    scalars = tuple(
        ScalarSignalMapping(
            str(item.get("channel")),
            source(item),
            number(item, "lower"),
            number(item, "upper"),
            neutral_epsilon(item),
        )
        for item in records("scalars")
    )
    splits = tuple(
        SplitSignalMapping(
            str(item.get("negative_channel")),
            str(item.get("positive_channel")),
            source(item),
            number(item, "lower"),
            number(item, "upper"),
        )
        for item in records("splits")
    )
    radial = tuple(
        RadialSignalGroup(
            tuple(item.get("channels", ())),
            number(item, "radius"),
            neutral_epsilon(item),
        )
        for item in records("radial_groups")
    )
    radial_sources = tuple(
        RadialSourceGroup(
            tuple(item.get("joints", ())),
            number(item, "radius"),
            neutral_epsilon(item),
        )
        for item in records("radial_source_groups")
    )
    events = tuple(
        PhysicalEventMapping(
            str(item.get("event")),
            source(item),
            number(item, "lower"),
            number(item, "upper"),
        )
        for item in records("physical_events")
    )
    return GamepadSignalController.xbox_one_s(
        axes, radial, scalars, splits, radial_sources, events
    )


def resolve_resource(profile: str, relative: str) -> Path:
    """Resolve one declared backend resource and fail if it is absent."""

    name = _relative_resource_name(relative, field="resource", profile=profile)
    try:
        path = Path(resource_path("mujoco", profile, name, must_exist=True))
    except MissingResourceError:
        raise
    except (OSError, ValueError) as exc:
        raise MissingResourceError(
            f"Cannot resolve MuJoCo resource {name!r} for profile {profile!r}: {exc}"
        ) from exc
    if not path.is_file():
        raise MissingResourceError(
            f"MuJoCo resource {name!r} for profile {profile!r} is not a file: {path}"
        )
    return path


def scene_resource(manifest: RuntimeManifest, scene: str) -> str:
    """Return the declared XML/MJZ file for a standalone scene name."""

    try:
        return manifest.scenes[scene]
    except KeyError as exc:
        available = ", ".join(sorted(manifest.scenes)) or "none"
        raise MissingResourceError(
            f"MuJoCo profile {manifest.profile!r} does not declare standalone "
            f"scene {scene!r}; available scenes: {available}."
        ) from exc


def _relative_resource_name(value: Any, *, field: str, profile: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssetImportError(
            f"MuJoCo profile {profile!r} must provide a non-empty {field!r}."
        )
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise AssetImportError(
            f"MuJoCo profile {profile!r} contains unsafe {field} path {value!r}."
        )
    return candidate.as_posix()


def _string_mapping(value: Any, field: str, profile: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise AssetImportError(
            f"MuJoCo profile {profile!r} field {field!r} must be an object."
        )
    result: dict[str, str] = {}
    for logical, physical in value.items():
        if not isinstance(logical, str) or not logical:
            raise AssetImportError(
                f"MuJoCo profile {profile!r} field {field!r} contains an "
                "empty or non-string logical name."
            )
        result[logical] = _relative_name(
            physical, field=f"{field}.{logical}", profile=profile
        )
    if len(set(result.values())) != len(result):
        raise AssetImportError(
            f"MuJoCo profile {profile!r} field {field!r} maps multiple logical "
            "names to the same compiled name."
        )
    return result


def _relative_name(value: Any, *, field: str, profile: str) -> str:
    if not isinstance(value, str) or not value:
        raise AssetImportError(
            f"MuJoCo profile {profile!r} binding {field!r} must be a non-empty string."
        )
    return value
