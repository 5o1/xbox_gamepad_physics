"""Standalone MuJoCo scene loading for the Xbox One S asset."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._backend import require_mujoco
from ._manifest import load_runtime_manifest, resolve_resource, scene_resource
from ._spec import compile_spec, load_spec, make_data
from .handle import MujocoGamepadHandle, bind_handle


@dataclass(frozen=True)
class LoadedScene:
    """A complete, compiled standalone MuJoCo scene and gamepad handle."""

    profile: str
    scene: str
    source_path: Path
    spec: Any
    model: Any
    data: Any
    gamepad: MujocoGamepadHandle


def load_scene(
    *,
    profile: str = "estimated_v0",
    scene: str = "fixed",
) -> LoadedScene:
    """Load and compile a declared standalone XML or MJZ scene.

    This API owns creation of the complete ``MjSpec``, ``MjModel``, and
    ``MjData``. Use :func:`attach_to_spec` when adding the gamepad to an
    existing robot scene.

    The repository currently ships readiness-gated placeholders. This call
    fails explicitly until the selected profile contains generated and
    validated physical resources, named bindings, and a standalone scene.
    """

    manifest = load_runtime_manifest(profile)
    relative = scene_resource(manifest, scene)
    source_path = resolve_resource(profile, relative)
    mujoco = require_mujoco()
    spec = load_spec(mujoco, source_path)
    model = compile_spec(spec, source=str(source_path))
    data = make_data(mujoco, model, source=str(source_path))
    handle = bind_handle(
        model,
        data,
        joints=manifest.joints,
        sensors=manifest.sensors,
    )
    return LoadedScene(
        profile=profile,
        scene=scene,
        source_path=source_path,
        spec=spec,
        model=model,
        data=data,
        gamepad=handle,
    )
