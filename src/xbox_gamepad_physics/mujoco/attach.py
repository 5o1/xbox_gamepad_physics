"""Attach a fresh gamepad fragment while preserving caller compilation ownership."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from xbox_gamepad_physics.errors import AssetImportError
from ._backend import require_mujoco
from ._spec import compile_spec, make_data
from .loader import GamepadSpec, make_spec


@dataclass(frozen=True)
class CompiledAttachment:
    model: Any
    data: Any
    gamepad: Any


@dataclass(frozen=True)
class GamepadAttachment:
    parent_spec: Any
    asset: GamepadSpec
    attached_frame: Any
    prefix: str
    suffix: str

    @property
    def child_spec(self):
        return self.asset.spec

    @property
    def source_path(self):
        return self.asset.source_path

    def bind(self, model, data, *, expected_external_masks=None):
        return self.asset.bind(model, data, prefix=self.prefix, suffix=self.suffix,
                               expected_external_masks=expected_external_masks)

    def compile(self):
        model = compile_spec(self.parent_spec, source="caller-owned parent MjSpec")
        data = make_data(require_mujoco(), model, source="caller-owned parent MjSpec")
        handle = self.bind(model, data)
        return CompiledAttachment(model, data, handle)


def attach_to_spec(parent_spec, *, frame=None, site=None, prefix="xbox_", suffix="",
                   profile="full_controls", resource_root=None, fixed_root=True,
                   pose=None, attach_visual=True, collision="coacd"):
    """Attach without compiling or modifying caller options or collision masks.

    No mount means a new frame directly under world. Free roots require this
    world mount. If a frame/site is supplied, pose is relative to that mount.
    Call bind after caller compilation to initialize this instance's controls
    from public physical initial positions; other caller objects retain state.
    """
    if frame is not None and site is not None:
        raise ValueError("Provide at most one mount frame or site")
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("prefix must be a non-empty string")
    if not isinstance(suffix, str):
        raise TypeError("suffix must be a string")
    if not fixed_root and (frame is not None or site is not None):
        raise ValueError("Free roots require a direct world mount; omit frame/site")
    asset = make_spec(resource_root=resource_root, profile=profile, fixed_root=fixed_root,
                      pose=pose, attach_visual=attach_visual, collision=collision)
    # Prevent a failed duplicate-name attach from partially editing the parent.
    for kind, names in (("joint", asset.manifest["bindings"]["joints"].values()),
                        ("actuator", asset.manifest["bindings"]["actuators"].values()),
                        ("body", asset.manifest["bindings"].get("bodies", {}).values())):
        accessor = getattr(parent_spec, kind)
        for name in names:
            if accessor(f"{prefix}{name}{suffix}") is not None:
                raise AssetImportError(f"MuJoCo attachment name already exists: {prefix}{name}{suffix}")
    if frame is None and site is None:
        frame = parent_spec.worldbody.add_frame()
    kwargs = {"prefix": prefix, "suffix": suffix}
    kwargs["frame" if frame is not None else "site"] = frame if frame is not None else site
    try:
        attached_frame = parent_spec.attach(asset.spec, **kwargs)
    except Exception as exc:
        raise AssetImportError(f"MuJoCo could not attach {asset.source_path}: {exc}") from exc
    return GamepadAttachment(parent_spec, asset, attached_frame, prefix, suffix)


def load_into_scene(scene, **kwargs):
    """Common lifecycle spelling; ``scene`` is an uncompiled caller MjSpec."""
    return attach_to_spec(scene, **kwargs)
