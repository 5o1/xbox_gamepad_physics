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
    default_collision: str | None = None
    min_sapien: str | None = None

    @property
    def physics_ready(self) -> bool:
        return self.available and self.dynamics_ready


def _manifest_error(backend: str, profile: str, detail: str) -> ProfileManifestError:
    return ProfileManifestError(f"invalid {backend}/{profile} manifest: {detail}")


def _validated_manifest(backend: str, profile: str, value: dict[str, Any]) -> BackendProfile:
    """Convert a built manifest; field formats are the generators' responsibility."""

    missing = tuple(field for field in _REQUIRED_FIELDS if field not in value)
    if missing:
        raise _manifest_error(backend, profile, f"missing fields {missing!r}")
    if value["schema_version"] != 1:
        raise _manifest_error(
            backend, profile, f"unsupported schema_version {value['schema_version']!r}"
        )
    if (value["asset_id"], value["backend"], value["profile"]) != ("xbox_one_s", backend, profile):
        raise _manifest_error(backend, profile, "asset/backend/profile identity mismatch")
    return BackendProfile(
        schema_version=value["schema_version"],
        asset_id=value["asset_id"],
        backend=backend,
        profile=profile,
        available=bool(value["available"]),
        dynamics_ready=bool(value["dynamics_ready"]),
        entrypoint=value["entrypoint"],
        required_files=tuple(value["required_files"]),
        reason=value["reason"],
        manifest_path=resource_path(backend, profile),
        default_collision=value.get("default_collision"),
        min_sapien=value.get("min_sapien"),
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
