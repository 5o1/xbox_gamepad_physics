"""Small, testable wrappers around the MjSpec loading API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xbox_gamepad_physics.errors import AssetImportError


def load_spec(mujoco: Any, path: Path) -> Any:
    """Load an XML or MJZ resource as an ``MjSpec``."""

    spec_type = getattr(mujoco, "MjSpec", None)
    if spec_type is None:
        raise AssetImportError(
            "The installed MuJoCo bindings do not expose MjSpec; install a "
            "MuJoCo release with model-editing and attachment support."
        )

    suffix = path.suffix.lower()
    try:
        if suffix == ".xml":
            return spec_type.from_file(str(path))
        if suffix == ".mjz":
            return spec_type.from_zip(str(path))
    except Exception as exc:
        raise AssetImportError(f"MuJoCo could not parse asset {path}: {exc}") from exc

    raise AssetImportError(
        f"Unsupported MuJoCo asset format for {path}; expected .xml or .mjz."
    )


def compile_spec(spec: Any, *, source: str) -> Any:
    """Compile an ``MjSpec`` and retain source context in failures."""

    compile_method = getattr(spec, "compile", None)
    if not callable(compile_method):
        raise AssetImportError(f"MuJoCo object loaded from {source} is not an MjSpec.")
    try:
        return compile_method()
    except Exception as exc:
        raise AssetImportError(f"MuJoCo could not compile {source}: {exc}") from exc


def make_data(mujoco: Any, model: Any, *, source: str) -> Any:
    """Allocate ``MjData`` with a source-aware project error."""

    data_type = getattr(mujoco, "MjData", None)
    if data_type is None:
        raise AssetImportError("The installed MuJoCo bindings do not expose MjData.")
    try:
        return data_type(model)
    except Exception as exc:
        raise AssetImportError(
            f"MuJoCo could not allocate runtime data for {source}: {exc}"
        ) from exc
