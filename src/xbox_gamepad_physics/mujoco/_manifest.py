"""Read and validate the MuJoCo-specific part of a backend profile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from xbox_gamepad_physics.errors import AssetImportError, MissingResourceError
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

    return RuntimeManifest(
        profile=profile,
        entrypoint=entrypoint,
        scenes=MappingProxyType(dict(scenes)),
        joints=MappingProxyType(dict(joints)),
        sensors=MappingProxyType(dict(sensors)),
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
