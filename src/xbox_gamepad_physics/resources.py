"""Safe access to backend artifacts shipped inside the Python package."""

from __future__ import annotations

import json
from pathlib import Path, PurePath
from typing import Any

from .errors import (
    ResourceFormatError,
    ResourceNotFoundError,
    UnsafeResourcePathError,
)


RESOURCE_ROOT = Path(__file__).resolve().parent / "resource_data"


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise UnsafeResourcePathError(f"{label} must be a non-empty string")
    path = PurePath(value)
    if (
        path.is_absolute()
        or len(path.parts) != 1
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise UnsafeResourcePathError(f"unsafe {label}: {value!r}")
    return value


def _safe_relative_parts(parts: tuple[str, ...]) -> tuple[str, ...]:
    if not parts:
        return ("manifest.json",)

    flattened: list[str] = []
    for value in parts:
        if not isinstance(value, str) or not value:
            raise UnsafeResourcePathError("resource path parts must be non-empty strings")
        normalized = value.replace("\\", "/")
        path = PurePath(normalized)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise UnsafeResourcePathError(f"unsafe resource path part: {value!r}")
        flattened.extend(path.parts)
    return tuple(flattened)


def resource_path(
    backend: str,
    profile: str,
    *parts: str,
    must_exist: bool = True,
) -> Path:
    """Resolve a resource beneath one backend/profile directory.

    With no ``parts``, the profile's ``manifest.json`` is returned.  Traversal
    through absolute paths, ``..`` components, or symlinks leaving the profile
    directory is rejected before the path is exposed to a simulator.
    """

    safe_backend = _safe_component(backend, "backend")
    safe_profile = _safe_component(profile, "profile")
    relative_parts = _safe_relative_parts(parts)

    resource_root = RESOURCE_ROOT.resolve()
    profile_root = (resource_root / safe_backend / safe_profile).resolve()
    try:
        profile_root.relative_to(resource_root)
    except ValueError as error:
        raise UnsafeResourcePathError(
            f"backend/profile path leaves the package resource root: "
            f"{safe_backend}/{safe_profile}"
        ) from error
    candidate = profile_root.joinpath(*relative_parts).resolve(strict=False)
    try:
        candidate.relative_to(profile_root)
    except ValueError as error:
        raise UnsafeResourcePathError(
            f"resource path leaves {safe_backend}/{safe_profile}: {parts!r}"
        ) from error

    if must_exist and not candidate.is_file():
        relative = "/".join((safe_backend, safe_profile, *relative_parts))
        raise ResourceNotFoundError(f"packaged resource does not exist: {relative}")
    return candidate


def load_json_resource(
    backend: str,
    profile: str,
    *parts: str,
) -> dict[str, Any]:
    """Load a packaged JSON object; malformed and non-object JSON fails closed."""

    path = resource_path(backend, profile, *parts)
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ResourceFormatError(f"cannot decode JSON resource {path}: {error}") from error
    if not isinstance(value, dict):
        raise ResourceFormatError(f"JSON resource must contain an object: {path}")
    return value
