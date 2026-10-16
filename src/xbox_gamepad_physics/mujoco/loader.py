"""Load generated M2 resources, then let the caller own compilation."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from xbox_gamepad_physics.backends.common.model import Pose
from xbox_gamepad_physics.backends.common.handle import ResetRequest
from xbox_gamepad_physics.backends.common.diagnostics import Finding
from xbox_gamepad_physics.errors import AssetImportError, MissingResourceError
from xbox_gamepad_physics.motion import motion_from_dict
from ._backend import require_mujoco
from ._spec import compile_spec, load_spec, make_data
from .handle import MujocoGamepadHandle, bind_handle
from .diagnostics import diagnose
from .numerics import numerical_policy, contact_policy


@dataclass(frozen=True)
class GamepadSpec:
    """An uncompiled, fresh asset fragment and its eventual name bindings."""
    spec: Any
    manifest: dict
    source_path: Path
    root_fixed: bool
    signal_controller: Any
    attach_visual: bool = True
    findings: tuple = ()

    @property
    def numerical_policy(self):
        return numerical_policy(self.manifest.get('backend_options', {}).get('mujoco'))

    @property
    def contact_policy(self):
        options = self.manifest.get('backend_options', {}).get('mujoco', {})
        return contact_policy(options) if 'contact_response' in options else None

    def bind(self, model, data, *, prefix="", suffix="", expected_external_masks=None):
        return bind(model, data, asset=self, prefix=prefix, suffix=suffix,
                    expected_external_masks=expected_external_masks)


@dataclass(frozen=True)
class LoadedScene:
    profile: str
    scene: str
    source_path: Path
    spec: Any
    model: Any
    data: Any
    gamepad: MujocoGamepadHandle


def _paths(resource_root, profile):
    if profile != "full_controls":
        raise ValueError("M2 supports only full_controls")
    if resource_root is None:
        from xbox_gamepad_physics.resources import resource_root as discover
        root = discover(backend="mujoco")
    else:
        root = Path(resource_root)
    artifact = root / "mujoco" / profile
    if (root / "manifest.json").is_file():
        artifact = root
        root = root.parent.parent
    path = artifact / "manifest.json"
    if not path.is_file():
        raise MissingResourceError(f"Build the M2 MuJoCo artifact first: {path}")
    manifest = json.loads(path.read_text())
    # Historical resources have a different identity and remain gated.
    if not manifest.get("bindings", {}).get("actuators"):
        raise AssetImportError("This is not a generated M2 full-controls artifact (no return actuator bindings)")
    entry = Path(manifest.get("entrypoint", "xbox_one_s.xml"))
    if entry.is_absolute() or ".." in entry.parts:
        raise AssetImportError("Unsafe MuJoCo manifest entrypoint")
    return root, artifact, manifest, artifact / entry


def make_spec(*, resource_root=None, profile="full_controls", fixed_root=True,
              pose=None, attach_visual=True, collision="coacd"):
    """Create a fragment with no global options, lights or cameras.

    Pose is local to the eventual mount; for a standalone fragment it is a
    world pose. A free root is added before compile and requires a world mount.
    ``resource_root`` accepts the common resource root or generated profile dir.
    """
    if collision != "coacd":
        raise ValueError("M2 supports frozen coacd collision only")
    if type(fixed_root) is not bool:
        raise TypeError("fixed_root must be bool")
    root, artifact, manifest, path = _paths(resource_root, profile)
    mj = require_mujoco()
    spec = load_spec(mj, path)
    bindings = manifest["bindings"]
    body_name = bindings.get("root_body", manifest.get("root_body", "controller_body"))
    body = spec.body(body_name)
    if pose is not None:
        pose = pose if isinstance(pose, Pose) else Pose(tuple(pose[:3]), tuple(pose[3:]))
        body.pos, body.quat = pose.position_m, pose.orientation_wxyz
    if not fixed_root:
        body.add_freejoint(name=bindings.get("root_joint", "root_free"))
    if not attach_visual:
        for geom in list(spec.geoms):
            if int(geom.group) == 1:
                spec.delete(geom)
    motion_path = root / manifest.get("motion_contract", f"common/xbox_one_s/motion/{profile}.json")
    motion = motion_from_dict(json.loads(motion_path.read_text()), profile)
    if set(bindings["joints"]) != set(motion.joint_by_name):
        raise AssetImportError("Generated bindings differ from the common motion contract")
    findings = ()
    if motion.joint_space_constraints:
        findings = (Finding("mechanical_joint_space_constraint_unmapped", "warning",
            "Common coupled radial constraints are projected for signals but are not mechanical MuJoCo constraints; mechanical equivalence is not established.",
            {"constraints": [dict(item) for item in motion.joint_space_constraints]}),)
    return GamepadSpec(spec, manifest, path, fixed_root, motion.signal_controller, attach_visual, findings)


def bind(model, data, *, asset: GamepadSpec, prefix="", suffix="", expected_external_masks=None):
    """Bind and initialize this instance from common physical initial positions.

    Only this instance's named control coordinates, velocities and targets are
    initialized. Caller objects and the structurally selected root are retained.
    """
    bindings = asset.manifest["bindings"]
    body_name = bindings.get("root_body", asset.manifest.get("root_body", "controller_body"))
    handle = bind_handle(model, data, joints=bindings["joints"],
        actuators=bindings["actuators"], sensors=bindings.get("sensors", {}),
        prefix=prefix, suffix=suffix, signal_controller=asset.signal_controller,
        profile=asset.manifest.get("profile", "full_controls"), root_body=body_name,
        root_joint=None if asset.root_fixed else bindings.get("root_joint", "root_free"),
        neutral_targets=asset.manifest.get("neutral_targets"),
        initial_positions=asset.manifest.get("initial_positions"))
    body_bindings = bindings.get("bodies", {body_name: body_name})
    body_names = [f"{prefix}{name}{suffix}" for name in body_bindings.values()]
    handle.findings = asset.findings + diagnose(model, body_names=body_names,
        attach_visual=asset.attach_visual, expected_external_masks=expected_external_masks,
        numerical_policy=asset.numerical_policy)
    handle.reset(ResetRequest())
    return handle


def load_standalone(*, resource_root=None, profile="full_controls", fixed_root=True,
                    pose=None, attach_visual=True, collision="coacd"):
    """Compile an asset-only standalone model and initialize this instance."""
    asset = make_spec(resource_root=resource_root, profile=profile, fixed_root=fixed_root,
                      pose=pose, attach_visual=attach_visual, collision=collision)
    mj = require_mujoco()
    # Standalone numerical settings match the generated standalone scenes.
    # These are integration choices, not measured gamepad physical parameters;
    # make_spec/attach never apply them to a caller-owned model.
    asset.spec.option.timestep = asset.numerical_policy['physics_timestep_s']
    asset.spec.option.integrator = mj.mjtIntegrator.mjINT_IMPLICITFAST
    model = compile_spec(asset.spec, source=str(asset.source_path))
    data = make_data(mj, model, source=str(asset.source_path))
    handle = asset.bind(model, data)
    mj.mj_forward(model, data)
    return LoadedScene(profile, "fixed" if fixed_root else "free", asset.source_path,
                       asset.spec, model, data, handle)


def load_scene(*, profile="full_controls", scene="fixed", resource_root=None):
    """Compatibility spelling for generated M2 standalone fixed/free models."""
    if scene not in {"fixed", "free"}:
        raise ValueError("scene must be fixed or free")
    return load_standalone(resource_root=resource_root, profile=profile, fixed_root=scene == "fixed")
