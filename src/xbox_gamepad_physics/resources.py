"""Lazy access to project-local built or downloaded backend resources."""

from __future__ import annotations

from functools import lru_cache
from contextlib import nullcontext
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import os
import re
import sys
import tempfile
import shutil
import urllib.request
import zipfile
from pathlib import Path, PurePath
from typing import Any

from .errors import (
    ResourceError,
    ResourceFormatError,
    ResourceNotFoundError,
    UnsafeResourcePathError,
)


from ._resource_cache import cache_lock, publish_directory

PACKAGE_ROOT = Path(__file__).resolve().parent
RESOURCE_ENV = "XBOX_GAMEPAD_PHYSICS_RESOURCES"


def package_version() -> str:
    """The package version; pyproject.toml is the single source in a checkout.

    In a checkout an editable install's metadata can lag behind the source,
    so the checkout's pyproject.toml wins; installed code uses its metadata.
    """

    repo = _repository()
    if repo is not None:
        match = re.search(r'^version\s*=\s*"([^"]+)"', (repo / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    try:
        return version("xbox-gamepad-physics")
    except PackageNotFoundError as error:
        raise ResourceError("cannot determine the package version; install the package or run from a checkout") from error


def release_url() -> str:
    value = package_version()
    return f"https://github.com/5o1/xbox_gamepad_physics/releases/download/v{value}/xbox_gamepad_physics-resources-{value}.zip"


def _ancestors(path: Path):
    return (path, *path.parents)


def _repository() -> Path | None:
    for candidate in (*_ancestors(PACKAGE_ROOT), *_ancestors(Path.cwd().resolve())):
        if (candidate / "assets").is_dir() and (candidate / "scripts/build_resources.py").is_file():
            return candidate
    return None


def _resolve_root() -> tuple[Path, str, Path | None]:
    explicit = os.environ.get(RESOURCE_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve(), "environment", _repository()
    repo = _repository()
    if repo is not None:
        return repo / "build/resources", "repository", repo
    for candidate in _ancestors(Path.cwd().resolve()):
        if (candidate / "pyproject.toml").is_file() or (candidate / ".git").exists():
            return candidate / ".xbox_gamepad_physics/resources", "project", None
    raise ResourceNotFoundError(
        f"cannot find a project root (pyproject.toml or .git); set {RESOURCE_ENV} to a resource directory"
    )


def _builder(repo: Path | None = None):
    from .builders import build_resources as builder
    return builder


def _build(root: Path, repo: Path | None = None, *, force: bool = False):
    return _builder(repo).build(output=root, inputs=_inputs(root, repo), force=force)


def _inputs(root: Path, repo: Path | None = None) -> Path:
    # A checkout may use the same approved inputs directly, without a release zip.
    return root / "inputs" if (root / ".input-release.json").is_file() else (repo or root / "inputs")


def missing_resources(root: Path) -> list[str]:
    """Inspect file presence, without hashes or simulator imports."""
    expected = {
        "kinematics/xbox_one_s.json",
        "kinematics/xbox_one_s_evidence.json",
        "kinematics/kinematics_build_audit.json",
        "common/xbox_one_s/motion/full_controls.json",
        "common/xbox_one_s/visual/manifest.json",
        "common/xbox_one_s/collision/manifest.json",
        "robotwin/left_stick/manifest.json",
        "robotwin/full_controls/manifest.json",
    }
    for relative in tuple(expected):
        path = root / relative
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            for name in value.get("required_files", []):
                expected.add((Path(relative).parent / name).as_posix())
            if relative == "common/xbox_one_s/visual/manifest.json":
                for part in value.get("parts", []):
                    expected.add("common/xbox_one_s/visual/" + part["file"])
                    for group in part.get("groups", []):
                        expected.add("common/xbox_one_s/visual/" + group["file"])
                expected.add("common/xbox_one_s/visual/meshes.bin")
                for name in value.get("source_textures", []):
                    expected.add("common/xbox_one_s/visual/" + name["file"])
                for name in value.get("sapien_material", {}).get("textures", {}).values():
                    expected.add("common/xbox_one_s/visual/" + name)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            raise ResourceFormatError(f"cannot inspect resource {path}: {error}") from error
    # Node receipts include new common sidecars without imposing them on old
    # third-party fixtures that intentionally provide a smaller declared graph.
    for stamp in (root / ".stamps").glob("*.json"):
        value = json.loads(stamp.read_text(encoding="utf-8"))
        output = value.get("fingerprint", {}).get("output")
        if output:
            expected.update((Path(output) / name).as_posix() for name in value.get("files", ()))
    return sorted(name for name in expected if not (root / name).is_file())


def resource_status(*, backends=("robotwin",), targets=None) -> dict:
    """Inspect resolution and staleness without acquiring or changing resources."""
    root, mode, repo = _resolve_root()
    statuses = _builder(repo).node_status(root, inputs=_inputs(root, repo), backends=backends, targets=targets)
    return {"root": str(root), "mode": mode, "nodes": statuses,
            "missing": missing_resources(root)}


def _lock() -> dict:
    path = PACKAGE_ROOT / "_resource_lock.json"
    if not path.is_file():
        raise ResourceNotFoundError("package has no _resource_lock.json; import the matching input archive after release packaging")
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock["version"] != package_version() or lock.get("kind") != "inputs":
        raise ResourceFormatError("resource lock must describe the matching version's input zip")
    return lock


def _input_current(root: Path, *, optional_files: tuple[str, ...] = ()) -> bool:
    marker = root / ".input-release.json"
    if not marker.is_file():
        return False
    try:
        receipt = json.loads(marker.read_text(encoding="utf-8"))
        lock = _lock()
        return (receipt["version"] == lock["version"] and receipt["sha256"] == lock["sha256"]
                and receipt["files"] == lock["files"]
                and all((root / "inputs" / name).is_file() for name in receipt["files"] if name not in optional_files))
    except (OSError, ValueError, KeyError):
        return False


def _import_archive(root: Path, archive: Path, lock: dict, *, locked: bool = False) -> None:
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock["sha256"]:
        raise ResourceFormatError("input zip SHA-256 mismatch")
    with (nullcontext() if locked else cache_lock(root)):
        with tempfile.TemporaryDirectory(prefix=root.name + ".import-", dir=root.parent) as directory:
            staged = Path(directory) / "resources"
            if root.exists():
                shutil.copytree(root, staged)
            else:
                staged.mkdir()
            inputs = staged / "inputs"
            if inputs.exists():
                shutil.rmtree(inputs)
            inputs.mkdir()
            with zipfile.ZipFile(archive) as zipped:
                names = []
                for member in zipped.infolist():
                    name = member.filename.replace("\\", "/")
                    path = PurePath(name)
                    if (path.is_absolute() or ".." in path.parts or ":" in name
                            or (member.external_attr >> 16) & 0o170000 == 0o120000):
                        raise UnsafeResourcePathError(f"unsafe input zip member: {name}")
                    names.append(name)
                if sorted(names) != sorted(lock["files"]):
                    raise ResourceFormatError("input zip members differ from the release whitelist")
                zipped.extractall(inputs)
            receipt = {key: lock[key] for key in ("version", "sha256", "files")}
            (staged / ".input-release.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            publish_directory(staged, root)


def _download(root: Path) -> None:
    """Download inputs direct first; use configured fallback only after failure."""
    lock = _lock()
    with cache_lock(root):
        if _input_current(root):
            return
        with tempfile.TemporaryDirectory(prefix=root.name + ".download-", dir=root.parent) as directory:
            archive = Path(directory) / "inputs.zip"
            direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                response = direct.open(lock["url"], timeout=60)
            except OSError as error:
                port = os.environ.get("FALLBACK_PROXY_PORT")
                if not port:
                    raise ResourceNotFoundError(f"direct input download failed: {error}; import with build-resources --archive <zip> --resources {root} --offline") from error
                print(f"direct input download failed: {error}; trying configured fallback", file=sys.stderr)
                proxy = f"http://127.0.0.1:{int(port)}"
                response = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})).open(lock["url"], timeout=60)
            with response, archive.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            _import_archive(root, archive, lock, locked=True)


def _acquire_inputs(root: Path, repo: Path | None, *, archive: Path | None = None,
             offline: bool = False, optional_files: tuple[str, ...] = ()) -> None:
    if archive is not None:
        try:
            _import_archive(root, Path(archive).expanduser().resolve(), _lock())
        except ResourceError:
            raise
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
            raise ResourceFormatError(f"cannot import input archive: {error}") from error
    elif not _input_current(root, optional_files=optional_files) and (repo is None or (root / ".input-release.json").exists()):
        if offline:
            raise ResourceNotFoundError(f"offline inputs missing or incomplete; use build-resources --archive <zip> --resources {root} --offline")
        _download(root)


def _prepare(root: Path, repo: Path | None, *, archive: Path | None = None,
             offline: bool = False, force: bool = False) -> None:
    _acquire_inputs(root, repo, archive=archive, offline=offline)
    try:
        _build(root, repo, force=force)
    except ResourceError:
        raise
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        raise ResourceFormatError(f"cannot prepare resources at {root}: {error}") from error


def prepare_inputs(*, resources: Path | None = None, archive: Path | None = None,
                   offline: bool = False, optional_files: tuple[str, ...] = ()) -> tuple[Path, Path]:
    """Acquire reviewed inputs; a viewer may tolerate its optional reference image missing."""
    root, _, repo = _resolve_root() if resources is None else (Path(resources).expanduser().resolve(), "explicit", _repository())
    _acquire_inputs(root, repo, archive=archive, offline=offline, optional_files=optional_files)
    return root, _inputs(root, repo)


@lru_cache(maxsize=1)
def resource_root() -> Path:
    """Resolve and prepare; existing environment roots also run the DAG."""
    root, _, repo = _resolve_root()
    _prepare(root, repo)
    return root


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
    prepare: bool = True,
) -> Path:
    """Resolve a resource beneath one backend/profile directory.

    With no ``parts``, the profile's ``manifest.json`` is returned.  Traversal
    through absolute paths, ``..`` components, or symlinks leaving the profile
    directory is rejected before the path is exposed to a simulator.
    """

    safe_backend = _safe_component(backend, "backend")
    if prepare and safe_backend in {"mujoco", "isaac"}:
        from .backends.registry import backend_spec
        backend_spec(safe_backend).require_builder_runtime()
    safe_profile = _safe_component(profile, "profile")
    relative_parts = _safe_relative_parts(parts)

    root = (resource_root() if prepare else _resolve_root()[0]).resolve()
    profile_root = (root / safe_backend / safe_profile).resolve()
    try:
        profile_root.relative_to(root)
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
        # Repair declared files deleted after first use; the resolved location
        # remains cached even when cwd or environment variables change.
        if prepare and relative in missing_resources(root):
            _prepare(root, _repository())
        if candidate.is_file():
            return candidate
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


def build_resources(*, force: bool = False, archive: Path | None = None,
                    resources: Path | None = None, offline: bool = False) -> Path:
    """Import a matching input zip and locally build all RoboTwin resources."""
    root, _, repo = _resolve_root() if resources is None else (Path(resources).expanduser().resolve(), "explicit", _repository())
    _prepare(root, repo, archive=archive, offline=offline, force=force)
    resource_root.cache_clear()
    return root


def query_resource_path(backend, profile, *parts, must_exist=True):
    """Inspect a location without acquiring inputs, building or starting a platform."""
    return resource_path(backend, profile, *parts, must_exist=must_exist, prepare=False)


def prepare_resources(*, backends=("robotwin",), targets=None, calibration=None,
                      runtime="python", resources=None, inputs=None,
                      archive=None, offline=False, force=False):
    """Prepare only the requested backend/target closure with explicit calibration."""
    from .backends.registry import backend_spec
    for name in backends:
        backend_spec(name).require_builder_runtime(runtime)
    from .backends.common.calibration import load_calibration, ResolvedCalibration
    if not isinstance(calibration, ResolvedCalibration):
        calibration = load_calibration(calibration)
        from .backends.common.calibration import resolve_calibration
        calibration = resolve_calibration(override=calibration, profile=calibration.profile)
    root, _, repo = (_resolve_root() if resources is None else
                     (Path(resources).expanduser().resolve(), "explicit", _repository()))
    if inputs is None:
        _acquire_inputs(root, repo, archive=archive, offline=offline)
        inputs = _inputs(root, repo)
    _builder(repo).build(output=root,inputs=Path(inputs),force=force,backends=backends,
                         targets=targets,runtime=runtime,calibration=calibration)
    resource_root.cache_clear()
    return root
