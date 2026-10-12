"""Direct package-resource loader for RoboTwin's SAPIEN scene.

This module has no module-level SAPIEN import, so the base package remains
usable for audits, exporters, and MuJoCo-only installations.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module, metadata
import re
import inspect
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from xbox_gamepad_physics.profiles import require_physics_ready
from xbox_gamepad_physics.resources import load_json_resource, resource_path
from xbox_gamepad_physics.controller import (
    AxisSignalMapping,
    GamepadSignalController,
    PhysicalEventMapping,
    RadialSourceGroup,
    RadialSignalGroup,
    ScalarSignalMapping,
    SplitSignalMapping,
)
from xbox_gamepad_physics.errors import (
    MissingBackendDependencyError,
    StateValidationError,
)
from xbox_gamepad_physics.motion import MotionJoint, load_motion_contract

from .articulation import (
    XboxOneSArticulation,
    joint_name,
)
from .errors import (
    ArticulationLoadError,
    JointConfigurationError,
    RoboTwinManifestError,
    SceneCompatibilityError,
)


_BACKEND = "robotwin"
@dataclass(frozen=True)
class JointDynamics:
    name: str
    stiffness: float
    damping: float
    force_limit: float
    friction: float
    target: float


@dataclass(frozen=True)
class RoboTwinAssetDescription:
    urdf_path: Path
    joint_dynamics: tuple[JointDynamics, ...]
    joint_motion: tuple[MotionJoint, ...]
    signal_controller: GamepadSignalController
    contact_material: "ContactMaterial"
    visual_binding: Mapping[str, Any]
    collision_variants: Mapping[str, Any]


@dataclass(frozen=True)
class ContactMaterial:
    static_friction: float
    dynamic_friction: float
    restitution: float
    contact_offset: float
    rest_offset: float


def _field(record: Any, key: str, context: str) -> Any:
    try:
        return record[key]
    except (KeyError, TypeError, IndexError) as error:
        raise RoboTwinManifestError(f"{context} missing required field {key!r}") from error


def _items(mapping: Mapping[str, Any], key: str) -> list[Any]:
    value = mapping.get(key, [])
    if not isinstance(value, list):
        raise RoboTwinManifestError(f"state_mapping.{key} must be a list")
    return value


def _signal_controller(mapping: Any) -> GamepadSignalController:
    """Build the controller; it validates channels, ranges and groups itself."""

    if not isinstance(mapping, Mapping):
        raise RoboTwinManifestError("ready RoboTwin profile needs state_mapping")
    context = "state_mapping"
    try:
        return GamepadSignalController.xbox_one_s(
            [
                AxisSignalMapping(_field(raw, "channel", context), _field(raw, "joint", context),
                                  _field(raw, "lower", context), _field(raw, "upper", context))
                for raw in _items(mapping, "axes")
            ],
            [
                RadialSignalGroup(tuple(_field(raw, "channels", context)), _field(raw, "radius", context),
                                  raw.get("neutral_epsilon", 0.0))
                for raw in _items(mapping, "radial_groups")
            ],
            [
                ScalarSignalMapping(_field(raw, "channel", context), _field(raw, "joint", context),
                                    _field(raw, "lower", context), _field(raw, "upper", context),
                                    raw.get("neutral_epsilon", 0.0))
                for raw in _items(mapping, "scalars")
            ],
            [
                SplitSignalMapping(_field(raw, "negative_channel", context),
                                   _field(raw, "positive_channel", context),
                                   _field(raw, "joint", context),
                                   _field(raw, "lower", context), _field(raw, "upper", context))
                for raw in _items(mapping, "splits")
            ],
            [
                RadialSourceGroup(tuple(_field(raw, "joints", context)), _field(raw, "radius", context),
                                  raw.get("neutral_epsilon", 0.0))
                for raw in _items(mapping, "radial_source_groups")
            ],
            [
                PhysicalEventMapping(_field(raw, "event", context), _field(raw, "joint", context),
                                     _field(raw, "lower", context), _field(raw, "upper", context))
                for raw in _items(mapping, "physical_events")
            ],
        )
    except StateValidationError as error:
        raise RoboTwinManifestError(f"invalid state_mapping: {error}") from error


def _validated_description(profile: str) -> RoboTwinAssetDescription:
    """Read a built RoboTwin profile.

    Field ranges and the explicit-physics URDF rules are guaranteed by the
    generators and checked by the asset tests at build time; here the loader
    only gates readiness and files, converts the manifest, and checks the
    joint names that form the public API.
    """

    ready = require_physics_ready(_BACKEND, profile)
    if not ready.entrypoint.endswith(".urdf"):
        raise RoboTwinManifestError("ready RoboTwin profile needs a .urdf entrypoint")
    manifest = load_json_resource(_BACKEND, profile)
    urdf_path = resource_path(_BACKEND, profile, ready.entrypoint).resolve(strict=True)

    raw_dynamics = _field(manifest, "joint_dynamics", "manifest")
    dynamics = tuple(
        JointDynamics(
            name=_field(raw, "name", f"joint_dynamics[{index}]"),
            **{
                key: float(_field(raw, key, f"joint_dynamics[{index}]"))
                for key in ("stiffness", "damping", "force_limit", "friction", "target")
            },
        )
        for index, raw in enumerate(raw_dynamics)
    )
    names = {item.name for item in dynamics}
    if len(names) != len(dynamics):
        raise RoboTwinManifestError("joint_dynamics contains duplicate joint names")

    joint_motion: tuple[MotionJoint, ...] = ()
    if manifest.get("motion_contract") is not None:
        motion_contract = load_motion_contract(profile)
        joint_motion = motion_contract.joints
        motion_names = set(motion_contract.joint_by_name)
        if motion_names != names:
            raise RoboTwinManifestError(
                "common motion/joint_dynamics name mismatch: "
                f"motion-only={sorted(motion_names - names)}, "
                f"profile-only={sorted(names - motion_names)}"
            )
        mapping = motion_contract.state_mapping
    else:
        mapping = manifest.get("state_mapping")
    signal_controller = _signal_controller(mapping)
    referenced = {
        item.source
        for group in (
            signal_controller.axis_mappings,
            signal_controller.scalar_mappings,
            signal_controller.split_mappings,
            signal_controller.physical_event_mappings,
        )
        for item in group
    }
    if not referenced <= names:
        raise RoboTwinManifestError(
            f"state_mapping references undeclared joints {sorted(referenced - names)}"
        )

    raw_contact = _field(manifest, "contact_material", "manifest")
    contact = ContactMaterial(
        static_friction=float(_field(raw_contact, "static_friction", "contact_material")),
        dynamic_friction=float(_field(raw_contact, "dynamic_friction", "contact_material")),
        restitution=float(_field(raw_contact, "restitution", "contact_material")),
        contact_offset=float(_field(raw_contact, "contact_offset_m", "contact_material")),
        rest_offset=float(_field(raw_contact, "rest_offset_m", "contact_material")),
    )
    return RoboTwinAssetDescription(
        urdf_path,
        dynamics,
        joint_motion,
        signal_controller,
        contact,
        _field(manifest, "visual_binding", "manifest"),
        manifest.get("collision_variants", {}),
    )


def _resolve_scene(scene_or_task: Any) -> Any:
    if callable(getattr(scene_or_task, "create_urdf_loader", None)):
        return scene_or_task
    nested = getattr(scene_or_task, "scene", None)
    if callable(getattr(nested, "create_urdf_loader", None)):
        return nested
    raise SceneCompatibilityError(
        "expected a SAPIEN Scene or a RoboTwin task exposing .scene"
    )


def _import_sapien() -> Any:
    try:
        module = import_module("sapien")
    except ModuleNotFoundError as error:
        if error.name != "sapien":
            raise
        raise MissingBackendDependencyError(
            "SAPIEN is required to convert a numeric pose; install it in the "
            "RoboTwin environment or pass an existing sapien.Pose"
        ) from error
    if hasattr(module, "Pose"):
        return module
    core = import_module("sapien.core")
    if not hasattr(core, "Pose"):
        raise SceneCompatibilityError("installed SAPIEN module does not expose Pose")
    return core


def _coerce_pose(pose: Any) -> Any:
    if hasattr(pose, "p") and hasattr(pose, "q"):
        return pose
    if isinstance(pose, Sequence) and not isinstance(pose, (str, bytes)):
        values = tuple(pose)
        if len(values) != 7:
            raise SceneCompatibilityError(
                "numeric pose must contain [x, y, z, qw, qx, qy, qz]"
            )
        try:
            numbers = tuple(float(value) for value in values)
        except (TypeError, ValueError) as error:
            raise SceneCompatibilityError("numeric pose contains a non-number") from error
        if not all(math.isfinite(value) for value in numbers):
            raise SceneCompatibilityError("numeric pose values must be finite")
        norm = math.sqrt(sum(value * value for value in numbers[3:]))
        if norm <= 1e-12:
            raise SceneCompatibilityError("pose quaternion must have non-zero norm")
        normalized_q = tuple(value / norm for value in numbers[3:])
        sapien = _import_sapien()
        return sapien.Pose(p=numbers[:3], q=normalized_q)
    raise SceneCompatibilityError(
        "pose must be a sapien.Pose or [x, y, z, qw, qx, qy, qz] sequence"
    )


def _looks_like_articulation(value: Any) -> bool:
    return callable(getattr(value, "get_active_joints", None)) and callable(
        getattr(value, "get_qpos", None)
    )


def _extract_one_articulation(load_result: Any) -> Any:
    found: list[Any] = []
    visited: set[int] = set()

    def visit(value: Any) -> None:
        identity = id(value)
        if identity in visited:
            return
        visited.add(identity)
        if _looks_like_articulation(value):
            found.append(value)
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(load_result)
    unique = {id(value): value for value in found}
    if len(unique) != 1:
        raise ArticulationLoadError(
            "URDF loader must return exactly one articulation; "
            f"found {len(unique)}"
        )
    return next(iter(unique.values()))


def _configure_joints(
    articulation: Any,
    dynamics: tuple[JointDynamics, ...],
    joint_motion: tuple[MotionJoint, ...],
    signal_controller: GamepadSignalController,
) -> XboxOneSArticulation:
    wrapper = XboxOneSArticulation(
        articulation,
        (configuration.name for configuration in dynamics),
        signal_controller,
    )
    joints = {joint_name(joint): joint for joint in articulation.get_active_joints()}
    motion_by_name = {item.name: item for item in joint_motion}
    for configuration in dynamics:
        joint = joints[configuration.name]
        motion = motion_by_name.get(configuration.name)
        if motion is not None:
            set_limits = getattr(joint, "set_limits", None)
            if not callable(set_limits):
                raise JointConfigurationError(
                    f"joint {configuration.name!r} cannot apply common motion limits"
                )
            set_limits([[motion.lower, motion.upper]])
        set_drive = getattr(joint, "set_drive_properties", None)
        set_friction = getattr(joint, "set_friction", None)
        set_target = getattr(joint, "set_drive_target", None)
        if not all(callable(method) for method in (set_drive, set_friction, set_target)):
            raise JointConfigurationError(
                f"joint {configuration.name!r} lacks a required SAPIEN drive method"
            )
        set_drive(
            configuration.stiffness,
            configuration.damping,
            force_limit=configuration.force_limit,
        )
        set_friction(configuration.friction)
        set_target(configuration.target)
    return wrapper


def _configure_contact_material(
    scene: Any, articulation: Any, configuration: ContactMaterial
) -> None:
    creator = getattr(scene, "create_physical_material", None)
    if not callable(creator):
        raise SceneCompatibilityError("SAPIEN scene lacks create_physical_material()")
    material = creator(
        configuration.static_friction,
        configuration.dynamic_friction,
        configuration.restitution,
    )
    links = articulation.get_links()
    for link in links:
        for shape in link.get_collision_shapes():
            shape.set_physical_material(material)
            shape.set_contact_offset(configuration.contact_offset)
            shape.set_rest_offset(configuration.rest_offset)
            groups = list(shape.get_collision_groups())
            groups[2] |= 0x80000000
            groups[3] = 0x5842
            shape.set_collision_groups(groups)


def _sdf_physx():
    sapien = _import_sapien()
    message = ("collision='sdf' requires SAPIEN >= 3.0.3 with SDF support; "
               'upgrade to SAPIEN 3.0.3 or explicitly pass collision="coacd"')
    installed = metadata.version("sapien")
    number = re.match(r"(\d+)\.(\d+)\.(\d+)", installed)
    if number is None or tuple(map(int, number.groups())) < (3, 0, 3):
        raise SceneCompatibilityError(message + f" (installed {installed})")
    physx = sapien.physx
    constructor = physx.PhysxCollisionShapeTriangleMesh.__init__
    try:
        has_parameter = "sdf" in inspect.signature(constructor).parameters
    except (TypeError, ValueError):
        has_parameter = "sdf:" in (constructor.__doc__ or "")
    if not has_parameter and not callable(getattr(physx, "set_sdf_config", None)):
        raise SceneCompatibilityError(message)
    return physx


def _load_sdf(loader, description, physx):
    variant = description.collision_variants.get("sdf")
    if variant is None:
        raise RoboTwinManifestError("profile does not declare an SDF collision variant")
    articulation_builders, actor_builders, cameras = loader.parse(str(description.urdf_path))
    if len(articulation_builders) != 1 or actor_builders or cameras:
        raise ArticulationLoadError("SDF gamepad URDF must contain one articulation and no actors or cameras")
    builder = articulation_builders[0]
    for link in builder.link_builders:
        link.collision_records.clear()
        for relative in variant["links"].get(link.name, []):
            link.add_nonconvex_collision_from_file(str(description.urdf_path.parent / relative))
    # SAPIEN 3.0.3 URDFLoader.parse has already set the root joint type and names.
    # Its load() lines 754–765 then call build() without overriding them.
    previous = physx.get_sdf_config()
    physx.set_sdf_config(spacing=variant["spacing_m"], subgrid_size=previous.subgridSize,
                         num_threads_for_construction=previous.num_threads_for_construction)
    try:
        return builder.build()
    finally:
        physx.set_sdf_config(previous)


def load_into_scene(
    scene: Any,
    pose: Any,
    fixed_root: bool,
    profile: str = "full_controls",
    attach_visual: bool = True,
    collision: str = "sdf",
) -> XboxOneSArticulation:
    """Load the packaged Xbox One S URDF into a caller-owned SAPIEN scene.

    ``scene`` may be a SAPIEN scene or an object exposing ``.scene``; passing
    ``task.scene`` is the stable, low-coupling RoboTwin path. ``pose`` is the
    caller-selected pose of the URDF ``controller_body`` root link in that
    scene. A numeric pose uses metres and ``[x, y, z, qw, qx, qy, qz]``.
    ``fixed_root`` is forwarded to the SAPIEN URDF loader.

    Loading bypasses RoboTwin's asset-directory helpers and articulation
    wrapper. Mass, center of mass, inertia, joint dynamics and visual binding
    remain backend resources; joint limits and signal constraints come from
    the public common motion contract.
    """

    if collision not in ("coacd", "sdf"):
        raise ValueError("collision must be 'coacd' or 'sdf'")
    if type(fixed_root) is not bool:
        raise TypeError("fixed_root must be bool")
    if type(attach_visual) is not bool:
        raise TypeError("attach_visual must be bool")
    description = _validated_description(profile)
    physx = _sdf_physx() if collision == "sdf" else None
    resolved_scene = _resolve_scene(scene)
    root_pose = _coerce_pose(pose)
    loader = resolved_scene.create_urdf_loader()
    if loader is None:
        raise SceneCompatibilityError("scene.create_urdf_loader() returned None")
    loader.fix_root_link = fixed_root
    loader.load_multiple_collisions_from_file = True

    load_multiple = getattr(loader, "load_multiple", None)
    load_single = getattr(loader, "load", None)
    if collision == "sdf":
        result = _load_sdf(loader, description, physx)
    elif callable(load_multiple):
        result = load_multiple(str(description.urdf_path))
    elif callable(load_single):
        result = load_single(str(description.urdf_path))
    else:
        raise SceneCompatibilityError(
            "SAPIEN URDF loader exposes neither load_multiple() nor load()"
        )
    articulation = _extract_one_articulation(result)

    set_pose = getattr(articulation, "set_root_pose", None)
    if not callable(set_pose):
        set_pose = getattr(articulation, "set_pose", None)
    if not callable(set_pose):
        raise ArticulationLoadError(
            "loaded articulation exposes neither set_root_pose() nor set_pose()"
        )
    set_pose(root_pose)
    _configure_contact_material(
        resolved_scene, articulation, description.contact_material
    )
    if attach_visual:
        from .visual import attach_visual_to_articulation

        attach_visual_to_articulation(articulation, description.visual_binding)
    return _configure_joints(
        articulation,
        description.joint_dynamics,
        description.joint_motion,
        description.signal_controller,
    )
