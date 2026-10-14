"""MuJoCo visual-only scene and attachment APIs.

These entry points expose the reviewed Xbox One S appearance asset. They do
not add collision geoms, joints, mass, inertia, or contact parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from xbox_gamepad_physics.errors import AssetImportError
from xbox_gamepad_physics.resources import resource_path

from ._backend import require_mujoco, reject_release_backend
from ._spec import compile_spec, load_spec, make_data


@dataclass(frozen=True)
class LoadedVisualScene:
    """Compiled standalone visual scene with initialized MuJoCo data."""

    scene: str
    renderer: str
    source_path: Path
    manifest: dict[str, Any]
    spec: Any
    model: Any
    data: Any

    @property
    def physics_ready(self) -> bool:
        return False


@dataclass(frozen=True)
class VisualAttachment:
    """A visual-only child attached to a caller-owned ``MjSpec``."""

    parent_spec: Any
    child_spec: Any
    attached_frame: Any
    source_path: Path
    renderer: str
    prefix: str
    suffix: str

    @property
    def physics_ready(self) -> bool:
        return False

    def compile(self) -> tuple[Any, Any]:
        """Compile the parent and initialize all position-dependent fields."""

        mujoco = require_mujoco()
        model = compile_spec(
            self.parent_spec, source="parent with Xbox One S visual"
        )
        data = make_data(mujoco, model, source="parent with Xbox One S visual")
        # Fixed cameras and geom world poses are undefined for rendering until
        # the first forward pass.
        mujoco.mj_forward(model, data)
        return model, data


def _visual_root() -> tuple[Path, dict[str, Any]]:
    manifest_path = resource_path("mujoco", "visual_v0", "visual_manifest.json")
    return manifest_path.parent, json.loads(manifest_path.read_text(encoding="utf-8"))


def _renderer_record(manifest: dict[str, Any], renderer: str) -> dict[str, Any]:
    records = manifest.get("renderers")
    if records is None and renderer == "classic":
        return {
            "entrypoint": manifest["entrypoint"],
            "scenes": manifest.get("scenes", {}),
        }
    if renderer not in (records or {}):
        expected = ", ".join(sorted(records or {"classic": None}))
        raise ValueError(
            f"unknown MuJoCo visual renderer {renderer!r}; expected {expected}"
        )
    return records[renderer]


def load_visual_scene(
    *, scene: str = "table", renderer: str = "classic"
) -> LoadedVisualScene:
    """Load the table review scene or the standalone visual asset."""

    reject_release_backend()

    root, manifest = _visual_root()
    record = _renderer_record(manifest, renderer)
    relative = (
        record["entrypoint"]
        if scene == "asset"
        else record.get("scenes", {}).get(scene)
    )
    if not relative:
        expected = ", ".join(["asset", *sorted(record.get("scenes", {}))])
        raise ValueError(
            f"unknown {renderer} MuJoCo visual scene {scene!r}; expected {expected}"
        )

    source = (root / relative).resolve(strict=True)
    mujoco = require_mujoco()
    spec = load_spec(mujoco, source)
    model = compile_spec(spec, source=str(source))
    data = make_data(mujoco, model, source=str(source))
    # Fixed cameras and geom world poses are undefined for rendering until the
    # first forward pass. Omitting this call produced an all-black first frame
    # in the native EGL verification run.
    mujoco.mj_forward(model, data)
    return LoadedVisualScene(scene, renderer, source, manifest, spec, model, data)


def attach_visual_to_spec(
    parent_spec: Any,
    *,
    frame: Any | None = None,
    site: Any | None = None,
    prefix: str = "xbox_visual_",
    suffix: str = "",
    renderer: str = "classic",
) -> VisualAttachment:
    """Attach the render-only asset to exactly one parent frame or site."""

    reject_release_backend()

    if (frame is None) == (site is None):
        raise ValueError("Exactly one of 'frame' and 'site' must be provided.")
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("'prefix' must be a non-empty string.")
    if not isinstance(suffix, str):
        raise TypeError("'suffix' must be a string.")

    attach_method = getattr(parent_spec, "attach", None)
    if not callable(attach_method):
        raise TypeError("parent_spec must expose the MuJoCo MjSpec.attach API.")

    root, manifest = _visual_root()
    record = _renderer_record(manifest, renderer)
    source = (root / record["entrypoint"]).resolve(strict=True)
    child = load_spec(require_mujoco(), source)
    kwargs: dict[str, Any] = {"prefix": prefix, "suffix": suffix}
    kwargs["frame" if frame is not None else "site"] = (
        frame if frame is not None else site
    )
    try:
        attached = attach_method(child, **kwargs)
    except Exception as exc:
        target = f"frame {frame!r}" if frame is not None else f"site {site!r}"
        raise AssetImportError(
            f"MuJoCo visual attachment failed at {target}: {exc}"
        ) from exc

    return VisualAttachment(
        parent_spec=parent_spec,
        child_spec=child,
        attached_frame=attached,
        source_path=source,
        renderer=renderer,
        prefix=prefix,
        suffix=suffix,
    )
