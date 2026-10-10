"""Lazy access to project-local built or downloaded backend resources."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.util
from importlib.metadata import version, PackageNotFoundError
import json
import os
import re
import sys
import tempfile
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


@lru_cache(maxsize=None)
def _builder(repo: Path):
    spec = importlib.util.spec_from_file_location("_xbox_resource_builder", repo / "scripts/build_resources.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def missing_resources(root: Path) -> list[str]:
    """Inspect file presence, without hashes or simulator imports."""
    expected = {
        "kinematics/xbox_one_s.json",
        "kinematics/xbox_one_s_evidence.json",
        "kinematics/kinematics_build_audit.json",
        "common/xbox_one_s/motion/full_controls.json",
        "common/xbox_one_s/visual/manifest.json",
        "mujoco/visual_v0/visual_manifest.json",
        "robotwin/left_stick/manifest.json",
        "robotwin/full_controls/manifest.json",
        "mujoco/full_controls/manifest.json",
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
                expected.add("common/xbox_one_s/visual/meshes.bin")
                for name in value.get("source_textures", []):
                    expected.add("common/xbox_one_s/visual/" + name["file"])
                for name in value.get("sapien_material", {}).get("textures", {}).values():
                    expected.add("common/xbox_one_s/visual/" + name)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            raise ResourceFormatError(f"cannot inspect resource {path}: {error}") from error
    marker = root / ".release.json"
    if marker.is_file():
        try:
            record = json.loads(marker.read_text(encoding="utf-8"))
            expected.update(record["files"])
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ResourceFormatError(f"invalid download receipt {marker}: {error}") from error
    return sorted(name for name in expected if not (root / name).is_file())


def resource_status() -> dict:
    """Inspect resolution and staleness without acquiring or changing resources."""
    root, mode, repo = _resolve_root()
    missing = missing_resources(root)
    if repo is not None:
        statuses = _builder(repo).node_status(root, repo=repo)
    else:
        # Installed mode: the release zip is replaced as a whole, so report it as one unit.
        marker = root / ".release.json"
        release = json.loads(marker.read_text(encoding="utf-8"))["version"] if marker.is_file() else None
        statuses = [{"name": "release", "version": release,
                     "stale": bool(missing) or release != package_version(), "missing": missing}]
    return {"root": str(root), "mode": mode, "nodes": statuses, "missing": missing}


def _download_current(root: Path) -> bool:
    if missing_resources(root):
        return False
    marker = root / ".release.json"
    return not marker.exists() or json.loads(marker.read_text(encoding="utf-8"))["version"] == package_version()


def _download(root: Path) -> None:
    url = release_url()
    try:
        lock_path = PACKAGE_ROOT / "_resource_lock.json"
        if not lock_path.is_file():
            raise ResourceNotFoundError(f"package has no _resource_lock.json; the release packaging step has not recorded zip integrity")
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if lock["version"] != package_version():
            raise ResourceFormatError("resource lock version differs from installed package")
        url = lock["url"]
        with cache_lock(root):
            if _download_current(root):
                return
            with tempfile.TemporaryDirectory(prefix=root.name + ".download-", dir=root.parent) as directory:
                temporary = Path(directory)
                archive = temporary / "release.zip"
                digest = hashlib.sha256()
                with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as stream:
                    total = response.headers.get("Content-Length", "unknown")
                    received = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        stream.write(chunk)
                        received += len(chunk)
                        print(f"resources download: {received}/{total} bytes", file=sys.stderr)
                if digest.hexdigest() != lock["sha256"]:
                    raise ResourceFormatError("resource zip SHA-256 mismatch")
                staged = temporary / "resources"
                staged.mkdir()
                with zipfile.ZipFile(archive) as zipped:
                    # Validating the archive boundary is required before extraction.
                    for member in zipped.infolist():
                        name = member.filename.replace("\\", "/")
                        path = PurePath(name)
                        if path.is_absolute() or ".." in path.parts or ":" in name or (member.external_attr >> 16) & 0o170000 == 0o120000:
                            raise UnsafeResourcePathError(f"unsafe release zip member: {name}")
                    zipped.extractall(staged)
                missing = missing_resources(staged)
                if missing:
                    raise ResourceFormatError(f"release zip lacks resources: {missing}")
                files = sorted(p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file())
                (staged / ".release.json").write_text(json.dumps({"version": lock["version"], "files": files}) + "\n", encoding="utf-8")
                publish_directory(staged, root)
    except (ResourceError, OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as error:
        kind = ResourceFormatError if isinstance(error, (ResourceFormatError, zipfile.BadZipFile)) else ResourceNotFoundError
        raise kind(f"resource download failed: {error}; URL: {url}; manually extract the release zip into {root}") from error


@lru_cache(maxsize=1)
def resource_root() -> Path:
    """Resolve and prepare once per process; never cache in HOME or the package."""
    root, mode, repo = _resolve_root()
    if mode == "environment" and root.is_dir():
        return root
    if mode == "repository":
        _builder(repo).build(output=root, repo=repo)
    elif not _download_current(root):
        if repo is not None:
            _builder(repo).build(output=root, repo=repo)
        else:
            _download(root)
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
) -> Path:
    """Resolve a resource beneath one backend/profile directory.

    With no ``parts``, the profile's ``manifest.json`` is returned.  Traversal
    through absolute paths, ``..`` components, or symlinks leaving the profile
    directory is rejected before the path is exposed to a simulator.
    """

    safe_backend = _safe_component(backend, "backend")
    safe_profile = _safe_component(profile, "profile")
    relative_parts = _safe_relative_parts(parts)

    root = resource_root().resolve()
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
        if relative in missing_resources(root):
            repo = _repository()
            if repo is not None:
                _builder(repo).build(output=root, repo=repo)
            else:
                _download(root)
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


def build_resources(*, force: bool = False) -> Path:
    """Explicit local build, requiring the repository's source and scripts."""
    root, _, repo = _resolve_root()
    if repo is None:
        raise ResourceNotFoundError("build-resources requires a repository checkout with assets/ and scripts/build_resources.py")
    _builder(repo).build(output=root, force=force, repo=repo)
    resource_root.cache_clear()
    return root
