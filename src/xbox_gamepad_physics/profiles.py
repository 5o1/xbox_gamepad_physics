"""Backend profile manifests and the fail-closed physics readiness gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PhysicsNotReadyError, ProfileManifestError, ResourceNotFoundError
from .resources import load_json_resource, resource_path


_REQUIRED_FIELDS = (
    "schema_version",
    "asset_id",
    "backend",
    "profile",
    "available",
    "dynamics_ready",
    "entrypoint",
    "required_files",
    "reason",
)


@dataclass(frozen=True, slots=True)
class BackendProfile:
    """Validated immutable view of one packaged backend profile."""

    schema_version: int
    asset_id: str
    backend: str
    profile: str
    available: bool
    dynamics_ready: bool
    entrypoint: str | None
    required_files: tuple[str, ...]
    reason: str | None
    manifest_path: Path

    @property
    def physics_ready(self) -> bool:
        return self.available and self.dynamics_ready


def _manifest_error(backend: str, profile: str, detail: str) -> ProfileManifestError:
    return ProfileManifestError(f"invalid {backend}/{profile} manifest: {detail}")


def _validated_manifest(backend: str, profile: str, value: dict[str, Any]) -> BackendProfile:
    missing = tuple(field for field in _REQUIRED_FIELDS if field not in value)
    if missing:
        raise _manifest_error(backend, profile, f"missing fields {missing!r}")

    if not isinstance(value["schema_version"], int) or isinstance(
        value["schema_version"], bool
    ):
        raise _manifest_error(backend, profile, "schema_version must be an integer")
    if value["schema_version"] != 1:
        raise _manifest_error(
            backend, profile, f"unsupported schema_version {value['schema_version']!r}"
        )
    if value["asset_id"] != "xbox_one_s":
        raise _manifest_error(backend, profile, "asset_id must be 'xbox_one_s'")
    if value["backend"] != backend or value["profile"] != profile:
        raise _manifest_error(backend, profile, "backend/profile identity mismatch")
    if type(value["available"]) is not bool or type(value["dynamics_ready"]) is not bool:
        raise _manifest_error(
            backend, profile, "available and dynamics_ready must be booleans"
        )

    entrypoint = value["entrypoint"]
    if entrypoint is not None and (not isinstance(entrypoint, str) or not entrypoint):
        raise _manifest_error(backend, profile, "entrypoint must be null or a path string")

    raw_required_files = value["required_files"]
    if not isinstance(raw_required_files, list) or not all(
        isinstance(item, str) and item for item in raw_required_files
    ):
        raise _manifest_error(backend, profile, "required_files must be a list of paths")
    if len(set(raw_required_files)) != len(raw_required_files):
        raise _manifest_error(backend, profile, "required_files contains duplicates")

    reason = value["reason"]
    is_ready = value["available"] and value["dynamics_ready"]
    if is_ready:
        if reason is not None and not isinstance(reason, str):
            raise _manifest_error(
                backend, profile, "reason must be null or a string for a ready profile"
            )
    elif not isinstance(reason, str) or not reason.strip():
        raise _manifest_error(
            backend, profile, "a blocked profile must state a non-empty reason"
        )

    # Validate path syntax now, including profiles that intentionally lack files.
    if entrypoint is not None:
        resource_path(backend, profile, entrypoint, must_exist=False)
    for required_file in raw_required_files:
        resource_path(backend, profile, required_file, must_exist=False)

    return BackendProfile(
        schema_version=value["schema_version"],
        asset_id=value["asset_id"],
        backend=backend,
        profile=profile,
        available=value["available"],
        dynamics_ready=value["dynamics_ready"],
        entrypoint=entrypoint,
        required_files=tuple(raw_required_files),
        reason=reason,
        manifest_path=resource_path(backend, profile),
    )


def load_profile(backend: str, profile: str) -> BackendProfile:
    """Load and validate one packaged backend profile manifest."""

    value = load_json_resource(backend, profile)
    return _validated_manifest(backend, profile, value)


def require_physics_ready(backend: str, profile: str) -> BackendProfile:
    """Return a profile only after all physical-loader gates pass.

    Readiness requires both explicit status flags, a declared entrypoint, and
    every declared runtime file to exist.  A loader must call this function
    before importing its simulator or compiling an artifact.
    """

    candidate = load_profile(backend, profile)
    if not candidate.physics_ready:
        raise PhysicsNotReadyError(
            f"physical backend profile {backend}/{profile} is blocked: "
            f"available={candidate.available}, "
            f"dynamics_ready={candidate.dynamics_ready}; {candidate.reason}"
        )
    if candidate.entrypoint is None:
        raise ProfileManifestError(
            f"ready profile {backend}/{profile} has no entrypoint"
        )
    if candidate.entrypoint not in candidate.required_files:
        raise ProfileManifestError(
            f"ready profile {backend}/{profile} does not list its entrypoint "
            "in required_files"
        )
    for required_file in candidate.required_files:
        try:
            resource_path(backend, profile, required_file)
        except ResourceNotFoundError as error:
            raise PhysicsNotReadyError(
                f"physical backend profile {backend}/{profile} is incomplete: "
                f"missing required file {required_file!r}"
            ) from error
    return candidate
