"""Public simulator-independent motion contract for the Xbox One S asset."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any, Mapping

from .controller import (
    AxisSignalMapping,
    GamepadSignalController,
    PhysicalEventMapping,
    RadialSignalGroup,
    RadialSourceGroup,
    ScalarSignalMapping,
    SplitSignalMapping,
)
from .errors import ResourceFormatError, StateValidationError
from .resources import load_json_resource


@dataclass(frozen=True, slots=True)
class MotionJoint:
    name: str
    kind: str
    parent: str
    child: str
    origin: tuple[float, float, float]
    axis: tuple[float, float, float]
    lower: float
    upper: float
    unit: str


@dataclass(frozen=True, slots=True)
class MotionContract:
    asset_id: str
    profile: str
    joints: tuple[MotionJoint, ...]
    joint_by_name: Mapping[str, MotionJoint]
    signal_controller: GamepadSignalController
    state_mapping: Mapping[str, Any]
    joint_space_constraints: tuple[Mapping[str, Any], ...]


def _number(record: Mapping[str, Any], field: str, context: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResourceFormatError(f"{context}.{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ResourceFormatError(f"{context}.{field} must be finite")
    return result


def load_motion_contract(profile: str = "full_controls") -> MotionContract:
    """Load the common motion contract consumed by every simulator backend."""

    raw = load_json_resource("common", "xbox_one_s", "motion", f"{profile}.json")
    if raw.get("asset_id") != "xbox_one_s" or raw.get("profile") != profile:
        raise ResourceFormatError("motion contract asset/profile identity mismatch")
    raw_joints = raw.get("joints")
    if not isinstance(raw_joints, list) or not raw_joints:
        raise ResourceFormatError("motion contract joints must be a non-empty list")
    joints = []
    by_name = {}
    for index, record in enumerate(raw_joints):
        context = f"joints[{index}]"
        if not isinstance(record, Mapping):
            raise ResourceFormatError(f"{context} must be an object")
        name = record.get("name")
        kind = record.get("type")
        parent = record.get("parent")
        child = record.get("child")
        unit = record.get("unit")
        origin = record.get("origin")
        axis = record.get("axis")
        if not isinstance(name, str) or not name or name in by_name:
            raise ResourceFormatError(f"{context}.name is invalid or duplicated")
        if kind not in {"revolute", "prismatic"}:
            raise ResourceFormatError(f"{context}.type is unsupported")
        if not isinstance(parent, str) or not parent or not isinstance(child, str) or not child:
            raise ResourceFormatError(f"{context} parent and child must be non-empty strings")
        if not isinstance(origin, list) or len(origin) != 3:
            raise ResourceFormatError(f"{context}.origin must contain three numbers")
        if unit not in {"rad", "m"}:
            raise ResourceFormatError(f"{context}.unit is unsupported")
        if not isinstance(axis, list) or len(axis) != 3:
            raise ResourceFormatError(f"{context}.axis must contain three numbers")
        axis_values = tuple(_number({"value": value}, "value", context) for value in axis)
        origin_values = tuple(_number({"value": value}, "value", context) for value in origin)
        if math.sqrt(sum(value * value for value in axis_values)) <= 1e-12:
            raise ResourceFormatError(f"{context}.axis must be non-zero")
        lower = _number(record, "lower", context)
        upper = _number(record, "upper", context)
        if lower >= upper:
            raise ResourceFormatError(f"{context} lower must be below upper")
        joint = MotionJoint(name, kind, parent, child, origin_values, axis_values, lower, upper, unit)
        joints.append(joint)
        by_name[name] = joint

    bindings = raw.get("bindings")
    if not isinstance(bindings, Mapping):
        raise ResourceFormatError("motion contract bindings must be an object")

    def records(field: str) -> list[Mapping[str, Any]]:
        value = bindings.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
            raise ResourceFormatError(f"bindings.{field} must be a list of objects")
        return value

    def source(record: Mapping[str, Any]) -> MotionJoint:
        name = record.get("joint")
        if name not in by_name:
            raise ResourceFormatError(f"binding references unknown joint {name!r}")
        return by_name[name]

    def epsilon(record: Mapping[str, Any]) -> float:
        value = record.get("neutral_epsilon", 0.0)
        return _number({"value": value}, "value", "neutral_epsilon")

    axes = tuple(
        AxisSignalMapping(str(item.get("channel")), (joint := source(item)).name, joint.lower, joint.upper)
        for item in records("axes")
    )
    scalars = tuple(
        ScalarSignalMapping(str(item.get("channel")), (joint := source(item)).name, joint.lower, joint.upper, epsilon(item))
        for item in records("scalars")
    )
    splits = tuple(
        SplitSignalMapping(str(item.get("negative_channel")), str(item.get("positive_channel")), (joint := source(item)).name, joint.lower, joint.upper)
        for item in records("splits")
    )
    radial = tuple(
        RadialSignalGroup(tuple(item.get("channels", ())), _number(item, "radius", "radial_group"), epsilon(item))
        for item in records("radial_groups")
    )
    radial_sources = tuple(
        RadialSourceGroup(tuple(item.get("joints", ())), _number(item, "radius", "radial_source_group"), epsilon(item))
        for item in records("radial_source_groups")
    )
    events = tuple(
        PhysicalEventMapping(str(item.get("event")), (joint := source(item)).name, joint.lower, joint.upper)
        for item in records("physical_events")
    )
    try:
        controller = GamepadSignalController.xbox_one_s(
            axes, radial, scalars, splits, radial_sources, events
        )
    except StateValidationError as error:
        raise ResourceFormatError(f"invalid motion signal bindings: {error}") from error
    constraints = raw.get("joint_space_constraints", [])
    if not isinstance(constraints, list) or any(not isinstance(item, Mapping) for item in constraints):
        raise ResourceFormatError("joint_space_constraints must be a list of objects")
    state_mapping = {
        "axes": [
            {"channel": item.channel, "joint": item.source, "lower": item.lower, "upper": item.upper}
            for item in axes
        ],
        "scalars": [
            {
                "channel": item.channel,
                "joint": item.source,
                "lower": item.lower,
                "upper": item.upper,
                "neutral_epsilon": item.neutral_epsilon,
            }
            for item in scalars
        ],
        "splits": [
            {
                "negative_channel": item.negative_channel,
                "positive_channel": item.positive_channel,
                "joint": item.source,
                "lower": item.lower,
                "upper": item.upper,
            }
            for item in splits
        ],
        "radial_groups": [
            {
                "channels": list(item.channels),
                "radius": item.radius,
                "neutral_epsilon": item.neutral_epsilon,
            }
            for item in radial
        ],
        "radial_source_groups": [
            {
                "joints": list(item.sources),
                "radius": item.radius,
                "neutral_epsilon": item.neutral_epsilon,
            }
            for item in radial_sources
        ],
        "physical_events": [
            {"event": item.event, "joint": item.source, "lower": item.lower, "upper": item.upper}
            for item in events
        ],
    }
    return MotionContract(
        asset_id="xbox_one_s",
        profile=profile,
        joints=tuple(joints),
        joint_by_name=MappingProxyType(by_name),
        signal_controller=controller,
        state_mapping=MappingProxyType(state_mapping),
        joint_space_constraints=tuple(MappingProxyType(dict(item)) for item in constraints),
    )
