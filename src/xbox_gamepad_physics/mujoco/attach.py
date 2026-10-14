"""Attach the Xbox One S model to a caller-owned MuJoCo ``MjSpec``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xbox_gamepad_physics.errors import AssetImportError

from ._backend import require_mujoco, reject_release_backend
from ._manifest import RuntimeManifest, load_runtime_manifest, resolve_resource
from ._spec import compile_spec, load_spec, make_data
from .handle import MujocoGamepadHandle, bind_handle


@dataclass(frozen=True)
class CompiledAttachment:
    """A caller-owned parent spec compiled after gamepad attachment."""

    model: Any
    data: Any
    gamepad: MujocoGamepadHandle


@dataclass(frozen=True)
class GamepadAttachment:
    """Attachment metadata retained until the parent model is compiled."""

    parent_spec: Any
    child_spec: Any
    attached_frame: Any
    profile: str
    source_path: Path
    prefix: str
    suffix: str
    _manifest: RuntimeManifest

    def bind(self, model: Any, data: Any) -> MujocoGamepadHandle:
        """Bind this instance to an already compiled parent by element names."""

        return bind_handle(
            model,
            data,
            joints=self._manifest.joints,
            sensors=self._manifest.sensors,
            prefix=self.prefix,
            suffix=self.suffix,
            signal_controller=self._manifest.signal_controller,
        )

    def compile(self) -> CompiledAttachment:
        """Compile the caller-owned parent spec and bind this gamepad instance."""

        mujoco = require_mujoco()
        model = compile_spec(self.parent_spec, source="attached parent MjSpec")
        data = make_data(mujoco, model, source="attached parent MjSpec")
        return CompiledAttachment(model=model, data=data, gamepad=self.bind(model, data))


def attach_to_spec(
    parent_spec: Any,
    *,
    frame: Any | None = None,
    site: Any | None = None,
    prefix: str = "xbox_",
    suffix: str = "",
    profile: str = "full_controls",
) -> GamepadAttachment:
    """Attach the gamepad child model to one parent frame or site.

    The function edits ``parent_spec`` and deliberately leaves compilation to
    the caller. Call the returned object's :meth:`GamepadAttachment.bind`
    after compiling, or use :meth:`GamepadAttachment.compile` as a convenience.
    Exactly one of ``frame`` and ``site`` is required. ``prefix`` must be
    non-empty so multiple attached assets cannot collide silently.

    The checked-in profile currently has no generated physical MJCF/MJZ. The
    repository readiness gate therefore raises before this function edits the
    parent spec.
    """

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

    manifest = load_runtime_manifest(profile)
    source_path = resolve_resource(profile, manifest.entrypoint)
    mujoco = require_mujoco()
    child_spec = load_spec(mujoco, source_path)

    kwargs: dict[str, Any] = {"prefix": prefix, "suffix": suffix}
    if frame is not None:
        kwargs["frame"] = frame
    else:
        kwargs["site"] = site
    try:
        attached_frame = attach_method(child_spec, **kwargs)
    except Exception as exc:
        target = f"frame {frame!r}" if frame is not None else f"site {site!r}"
        raise AssetImportError(
            f"MuJoCo could not attach {source_path} to parent {target}: {exc}"
        ) from exc

    return GamepadAttachment(
        parent_spec=parent_spec,
        child_spec=child_spec,
        attached_frame=attached_frame,
        profile=profile,
        source_path=source_path,
        prefix=prefix,
        suffix=suffix,
        _manifest=manifest,
    )
