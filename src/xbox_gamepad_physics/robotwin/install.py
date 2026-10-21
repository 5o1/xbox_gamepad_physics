"""Optional explicit-copy installer for RoboTwin's native asset directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from xbox_gamepad_physics.profiles import load_profile
from xbox_gamepad_physics.resources import resource_path

from .errors import NativeInstallError


@dataclass(frozen=True)
class CopyOperation:
    source: Path
    destination: Path


@dataclass(frozen=True)
class NativeInstallResult:
    destination: Path
    operations: tuple[CopyOperation, ...]
    dry_run: bool


def install_native_assets(
    robotwin_root: str | Path,
    profile: str,
    *,
    dry_run: bool,
    overwrite: bool = False,
) -> NativeInstallResult:
    """Plan or execute a file copy into ``assets/objects/xbox_one_s``.

    ``dry_run`` has no default so callers must explicitly choose inspection or
    mutation.  The helper copies data files only and never patches RoboTwin
    Python modules, configuration, or task discovery code.
    """

    ready = load_profile("robotwin", profile)
    if ready.entrypoint != "mobility.urdf":
        raise NativeInstallError(
            "native RoboTwin installation requires entrypoint='mobility.urdf'"
        )
    root = Path(robotwin_root).expanduser().resolve()
    objects = root / "assets" / "objects"
    if not objects.is_dir():
        raise NativeInstallError(
            f"RoboTwin assets/objects directory does not exist: {objects}"
        )
    destination = objects / "xbox_one_s"
    relative_files = tuple(dict.fromkeys((*ready.required_files, "manifest.json")))
    operations = tuple(
        CopyOperation(
            resource_path("robotwin", profile, relative, must_exist=True),
            destination / relative,
        )
        for relative in relative_files
    )
    collisions = [item.destination for item in operations if item.destination.exists()]
    if collisions and not overwrite:
        raise NativeInstallError(
            "native asset destination already contains files; pass overwrite=True "
            f"after review: {collisions}"
        )
    if not dry_run:
        for operation in operations:
            operation.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(operation.source, operation.destination)
    return NativeInstallResult(destination, operations, dry_run)
