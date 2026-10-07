"""Direct package-resource loader for RoboTwin's SAPIEN scene.

This module has no module-level SAPIEN import, so the base package remains
usable for audits, exporters, and MuJoCo-only installations.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import math
from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

from xbox_gamepad_physics.profiles import require_physics_ready
from xbox_gamepad_physics.resources import load_json_resource, resource_path
from xbox_gamepad_physics.errors import MissingBackendDependencyError

from .articulation import XboxOneSArticulation, joint_name
from .errors import (
    ArticulationLoadError,
    JointConfigurationError,
    RoboTwinManifestError,
    SceneCompatibilityError,
)


_BACKEND = "robotwin"
_ASSET_ID = "xbox_one_s"
_JOINT_FIELDS = (
    "name",
    "stiffness",
    "damping",
    "force_limit",
    "friction",
    "target",
)


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


def _number(record: Mapping[str, Any], field: str, joint: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoboTwinManifestError(
            f"joint_dynamics[{joint!r}].{field} must be a finite number"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RoboTwinManifestError(
            f"joint_dynamics[{joint!r}].{field} must be a finite number"
        )
    return number


def _validated_description(profile: str) -> RoboTwinAssetDescription:
    """Gate readiness first, then validate every RoboTwin-specific field."""

    ready = require_physics_ready(_BACKEND, profile)
    manifest = load_json_resource(_BACKEND, profile)
    if manifest.get("asset_id") != _ASSET_ID:
        raise RoboTwinManifestError(
            f"expected asset_id {_ASSET_ID!r}, got {manifest.get('asset_id')!r}"
        )
    if manifest.get("backend") != _BACKEND:
        raise RoboTwinManifestError(
            f"expected backend {_BACKEND!r}, got {manifest.get('backend')!r}"
        )
    if manifest.get("profile") != profile:
        raise RoboTwinManifestError(
            f"manifest profile {manifest.get('profile')!r} does not match {profile!r}"
        )

    entrypoint = ready.entrypoint
    if not isinstance(entrypoint, str) or not entrypoint.endswith(".urdf"):
        raise RoboTwinManifestError("ready RoboTwin profile needs a .urdf entrypoint")
    if entrypoint not in ready.required_files:
        raise RoboTwinManifestError("entrypoint must be listed in required_files")

    for relative in ready.required_files:
        resource_path(_BACKEND, profile, relative, must_exist=True)
    urdf_path = resource_path(
        _BACKEND, profile, entrypoint, must_exist=True
    ).resolve(strict=True)
    if not urdf_path.is_absolute():  # defensive: Path.resolve() must guarantee this
        raise RoboTwinManifestError("resolved URDF path is not absolute")

    raw_dynamics = manifest.get("joint_dynamics")
    if not isinstance(raw_dynamics, list) or not raw_dynamics:
        raise RoboTwinManifestError(
            "ready RoboTwin profile needs a non-empty joint_dynamics list"
        )
    dynamics: list[JointDynamics] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_dynamics):
        if not isinstance(raw, dict):
            raise RoboTwinManifestError(
                f"joint_dynamics[{index}] must be an object"
            )
        missing = [field for field in _JOINT_FIELDS if field not in raw]
        if missing:
            raise RoboTwinManifestError(
                f"joint_dynamics[{index}] missing required fields {missing}"
            )
        name = raw["name"]
        if not isinstance(name, str) or not name:
            raise RoboTwinManifestError(
                f"joint_dynamics[{index}].name must be a non-empty string"
            )
        if name in names:
            raise RoboTwinManifestError(f"duplicate joint dynamics name {name!r}")
        names.add(name)
        item = JointDynamics(
            name=name,
            stiffness=_number(raw, "stiffness", name),
            damping=_number(raw, "damping", name),
            force_limit=_number(raw, "force_limit", name),
            friction=_number(raw, "friction", name),
            target=_number(raw, "target", name),
        )
        if item.stiffness < 0 or item.damping < 0 or item.friction < 0:
            raise RoboTwinManifestError(
                f"joint {name!r} stiffness, damping, and friction must be non-negative"
            )
        if item.force_limit <= 0:
            raise RoboTwinManifestError(
                f"joint {name!r} force_limit must be positive"
            )
        dynamics.append(item)
    description = RoboTwinAssetDescription(urdf_path, tuple(dynamics))
    _validate_urdf_physics(description)
    return description


def _xml_number(element: ET.Element, attribute: str, context: str) -> float:
    raw = element.get(attribute)
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise RoboTwinManifestError(
            f"{context} needs finite numeric attribute {attribute!r}"
        ) from error
    if not math.isfinite(value):
        raise RoboTwinManifestError(
            f"{context} needs finite numeric attribute {attribute!r}"
        )
    return value


def _xml_vector(
    element: ET.Element, attribute: str, length: int, context: str
) -> tuple[float, ...]:
    raw = element.get(attribute)
    if not isinstance(raw, str):
        raise RoboTwinManifestError(f"{context} needs attribute {attribute!r}")
    try:
        values = tuple(float(value) for value in raw.split())
    except ValueError as error:
        raise RoboTwinManifestError(
            f"{context}.{attribute} must contain {length} finite numbers"
        ) from error
    if len(values) != length or not all(math.isfinite(value) for value in values):
        raise RoboTwinManifestError(
            f"{context}.{attribute} must contain {length} finite numbers"
        )
    return values


def _validate_urdf_physics(description: RoboTwinAssetDescription) -> None:
    """Reject URDFs that would make SAPIEN invent physical defaults."""

    try:
        root = ET.parse(description.urdf_path).getroot()
    except (ET.ParseError, OSError) as error:
        raise RoboTwinManifestError(
            f"cannot parse RoboTwin URDF {description.urdf_path}: {error}"
        ) from error
    if root.tag != "robot":
        raise RoboTwinManifestError("RoboTwin entrypoint root element must be <robot>")

    links = root.findall("link")
    if not links:
        raise RoboTwinManifestError("RoboTwin URDF contains no links")
    link_names: set[str] = set()
    collision_count = 0
    for link in links:
        name = link.get("name")
        if not isinstance(name, str) or not name:
            raise RoboTwinManifestError("every URDF link needs a non-empty name")
        if name in link_names:
            raise RoboTwinManifestError(f"duplicate URDF link name {name!r}")
        link_names.add(name)
        inertial = link.find("inertial")
        mass = inertial.find("mass") if inertial is not None else None
        inertia = inertial.find("inertia") if inertial is not None else None
        inertial_origin = inertial.find("origin") if inertial is not None else None
        if (
            inertial is None
            or inertial_origin is None
            or mass is None
            or inertia is None
        ):
            raise RoboTwinManifestError(
                f"URDF link {name!r} needs explicit inertial origin, mass, and inertia"
            )
        _xml_vector(inertial_origin, "xyz", 3, f"link {name!r} inertial origin")
        _xml_vector(inertial_origin, "rpy", 3, f"link {name!r} inertial origin")
        mass_value = _xml_number(mass, "value", f"link {name!r} mass")
        if mass_value <= 0:
            raise RoboTwinManifestError(f"URDF link {name!r} mass must be positive")
        ixx, ixy, ixz, iyy, iyz, izz = (
            _xml_number(inertia, field, f"link {name!r} inertia")
            for field in ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")
        )
        leading_minor_2 = ixx * iyy - ixy * ixy
        determinant = (
            ixx * (iyy * izz - iyz * iyz)
            - ixy * (ixy * izz - iyz * ixz)
            + ixz * (ixy * iyz - iyy * ixz)
        )
        if ixx <= 0 or leading_minor_2 <= 0 or determinant <= 0:
            raise RoboTwinManifestError(
                f"URDF link {name!r} inertia tensor must be positive definite"
            )
        collision_count += len(link.findall("collision"))
    if collision_count == 0:
        raise RoboTwinManifestError("ready RoboTwin URDF contains no collision geometry")

    active_names: set[str] = set()
    for joint in root.findall("joint"):
        name = joint.get("name")
        kind = joint.get("type")
        if not isinstance(name, str) or not name:
            raise RoboTwinManifestError("every URDF joint needs a non-empty name")
        parent = joint.find("parent")
        child = joint.find("child")
        if parent is None or parent.get("link") not in link_names:
            raise RoboTwinManifestError(f"joint {name!r} has an invalid parent link")
        if child is None or child.get("link") not in link_names:
            raise RoboTwinManifestError(f"joint {name!r} has an invalid child link")
        origin = joint.find("origin")
        if origin is None:
            raise RoboTwinManifestError(f"joint {name!r} needs an explicit origin")
        _xml_vector(origin, "xyz", 3, f"joint {name!r} origin")
        _xml_vector(origin, "rpy", 3, f"joint {name!r} origin")
        if kind == "fixed":
            continue
        if kind not in {"revolute", "continuous", "prismatic"}:
            raise RoboTwinManifestError(
                f"joint {name!r} has unsupported active type {kind!r}"
            )
        if name in active_names:
            raise RoboTwinManifestError(f"duplicate active URDF joint name {name!r}")
        active_names.add(name)
        axis = joint.find("axis")
        if axis is None:
            raise RoboTwinManifestError(f"joint {name!r} needs an explicit axis")
        axis_vector = _xml_vector(axis, "xyz", 3, f"joint {name!r} axis")
        if math.sqrt(sum(value * value for value in axis_vector)) <= 1e-12:
            raise RoboTwinManifestError(f"joint {name!r} axis must be non-zero")
        limit = joint.find("limit")
        if limit is None:
            raise RoboTwinManifestError(f"joint {name!r} needs explicit limits")
        effort = _xml_number(limit, "effort", f"joint {name!r} limit")
        velocity = _xml_number(limit, "velocity", f"joint {name!r} limit")
        if effort <= 0 or velocity <= 0:
            raise RoboTwinManifestError(
                f"joint {name!r} effort and velocity limits must be positive"
            )
        if kind != "continuous":
            lower = _xml_number(limit, "lower", f"joint {name!r} limit")
            upper = _xml_number(limit, "upper", f"joint {name!r} limit")
            if lower >= upper:
                raise RoboTwinManifestError(
                    f"joint {name!r} lower limit must be smaller than upper"
                )

    declared_names = {item.name for item in description.joint_dynamics}
    if active_names != declared_names:
        raise RoboTwinManifestError(
            "URDF/joint_dynamics name mismatch: "
            f"URDF-only={sorted(active_names - declared_names)}, "
            f"profile-only={sorted(declared_names - active_names)}"
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
    articulation: Any, dynamics: tuple[JointDynamics, ...]
) -> XboxOneSArticulation:
    wrapper = XboxOneSArticulation(
        articulation, (configuration.name for configuration in dynamics)
    )
    joints = {joint_name(joint): joint for joint in articulation.get_active_joints()}
    for configuration in dynamics:
        joint = joints[configuration.name]
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


def load_into_scene(
    scene: Any,
    pose: Any,
    fixed_root: bool,
    profile: str,
) -> XboxOneSArticulation:
    """Load the packaged Xbox One S URDF directly into a SAPIEN scene.

    Loading bypasses RoboTwin's ``create_sapien_urdf_obj`` and its articulation
    wrapper.  Consequently the mass, center of mass, and inertia authored in
    the URDF remain untouched.
    """

    if type(fixed_root) is not bool:
        raise TypeError("fixed_root must be bool")
    description = _validated_description(profile)
    resolved_scene = _resolve_scene(scene)
    root_pose = _coerce_pose(pose)
    loader = resolved_scene.create_urdf_loader()
    if loader is None:
        raise SceneCompatibilityError("scene.create_urdf_loader() returned None")
    loader.fix_root_link = fixed_root
    loader.load_multiple_collisions_from_file = True

    load_multiple = getattr(loader, "load_multiple", None)
    load_single = getattr(loader, "load", None)
    if callable(load_multiple):
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
    return _configure_joints(articulation, description.joint_dynamics)
