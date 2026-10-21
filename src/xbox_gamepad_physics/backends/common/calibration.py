"""Explicit, instance-scoped calibration with atomic validation and provenance."""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Mapping

from .model import Evidence, Parameter

SCHEMA = "backend-calibration-v1"
_FORBIDDEN = {"travel", "travel_m", "travel_rad", "limits", "joint_limits", "range", "ranges", "lower", "upper", "half_sweep_rad", "kinematics", "motion"}
_JOINT_UNITS = {"stiffness": ("N/m", "N*m/rad"), "endpoint_force": ("N", "N*m"), "drive_damping": ("N*s/m", "N*m*s/rad"), "passive_damping": ("N*s/m", "N*m*s/rad"), "neutral_target": ("m", "rad"), "preload_fraction": ("1",), "effort_limit": ("N", "N*m"), "dry_friction_effort": ("N", "N*m")}
_CONTACT_UNITS = {"static_friction": ("1",), "dynamic_friction": ("1",), "restitution": ("1",), "rolling_resistance_length": ("m",), "torsional_resistance_length": ("m",)}


@dataclass(frozen=True)
class CalibrationOverride:
    schema_version: str = SCHEMA
    asset_id: str = "xbox_one_s"
    profile: str = "full_controls"
    physical: Mapping[str, object] = field(default_factory=dict)
    signal_policy: Mapping[str, object] = field(default_factory=dict)
    spawn: Mapping[str, object] = field(default_factory=dict)
    backend_options: Mapping[str, Mapping[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedCalibration:
    asset_id: str
    profile: str
    configuration_id: str
    motion_revision: str
    physical: Mapping[str, Parameter]
    signal_policy: Mapping[str, object]
    spawn: Mapping[str, object]
    backend_options: Mapping[str, Mapping[str, object]]
    source_chain: Mapping[str, tuple[Evidence, ...]]


def _reject_structure(raw, path="calibration"):
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if key in _FORBIDDEN or key.startswith("travel_") or key.endswith("_limits"):
                raise ValueError(f"{path}.{key}: travel/joint-range overrides are not supported; no overrides were applied")
            if key != "evidence":
                _reject_structure(value, f"{path}.{key}")


def _validate(raw: Mapping[str, object]) -> CalibrationOverride:
    _reject_structure(raw)
    allowed = set(CalibrationOverride.__dataclass_fields__)
    if set(raw) - allowed:
        raise ValueError(f"unknown calibration fields: {sorted(set(raw) - allowed)}")
    value = CalibrationOverride(**raw)
    if value.schema_version != SCHEMA or value.asset_id != "xbox_one_s" or value.profile not in {"full_controls", "left_stick"}:
        raise ValueError("calibration schema, asset or profile mismatch")
    if set(value.physical) - {"joints", "contact_materials"}:
        raise ValueError("Physical overrides support joints and contact_materials only")
    for group, units in (("joints", _JOINT_UNITS), ("contact_materials", _CONTACT_UNITS)):
        records = value.physical.get(group, {})
        if not isinstance(records, Mapping):
            raise ValueError(f"physical.{group} must be an object")
        for name, record in records.items():
            if not isinstance(record, Mapping) or set(record) - set(units):
                raise ValueError(f"physical.{group}.{name}: unsupported parameter")
            for key, item in record.items():
                parameter = Parameter.from_dict(item)
                if parameter.unit not in units[key]:
                    raise ValueError(f"physical.{group}.{name}.{key}: incorrect unit {parameter.unit!r}")
                if parameter.value is not None:
                    if isinstance(parameter.value, (list, tuple)):
                        raise ValueError(f"{key} must be scalar")
                    if key != "neutral_target" and parameter.value < 0:
                        raise ValueError(f"{key} must be nonnegative")
                    if key in {"restitution", "preload_fraction"} and parameter.value > 1:
                        raise ValueError(f"{key} must be within [0,1]")
            if "stiffness" in record and "endpoint_force" in record:
                raise ValueError("specify endpoint_force or stiffness, not both")
    for namespace in (value.signal_policy, value.spawn, value.backend_options):
        if not isinstance(namespace, Mapping):
            raise ValueError("calibration namespaces must be objects")
    if value.signal_policy or value.spawn:
        raise ValueError("Calibration supports physical properties and backend mappings only; signal/spawn overrides are not supported")
    if "root_mode" in value.spawn and value.spawn["root_mode"] not in {"fixed", "free"}:
        raise ValueError("spawn.root_mode must be fixed or free")
    return value


def load_calibration(path: Path | None = None) -> CalibrationOverride:
    """Use an explicit path instead of the environment file, never merge both."""
    selected = path if path is not None else os.environ.get("XBOX_GAMEPAD_PHYSICS_CALIBRATION")
    return _validate(json.loads(Path(selected).read_text(encoding="utf-8"))) if selected else CalibrationOverride()


def resolve_calibration(references: Mapping[str, Parameter] | None = None, override: CalibrationOverride | None = None, *, overrides: Mapping[str, object] | None = None, profile: str = "full_controls", motion_revision: str = "motion-v1") -> ResolvedCalibration:
    """Resolve reference < file < explicit values without losing explicit nulls."""
    selected = override if override is not None else load_calibration()
    _validate(asdict(selected))
    if selected.profile != profile:
        # An absent file is an empty override, independent of selected profile.
        if asdict(selected) != asdict(CalibrationOverride()):
            raise ValueError("calibration profile mismatch")
    physical = dict(references or {})
    chain = {key: item.evidence for key, item in physical.items()}
    namespaces = {"signal_policy": dict(selected.signal_policy), "spawn": dict(selected.spawn), "backend_options": dict(selected.backend_options)}
    layers = [selected]
    if overrides is not None:
        layers.append(_validate({"profile": profile, **overrides}))
    for layer in layers:
        for group, records in layer.physical.items():
            for name, record in records.items():
                for key, item in record.items():
                    path = f"{group}.{name}.{key}"
                    parameter = Parameter.from_dict(item)
                    physical[path] = parameter
                    chain[path] = chain.get(path, ()) + parameter.evidence
        for name in namespaces:
            namespaces[name].update(getattr(layer, name))
    for path in physical:
        if path.endswith(".stiffness") and path[:-len("stiffness")] + "endpoint_force" in physical:
            raise ValueError("effective calibration must specify endpoint_force or stiffness, not both")
    payload = {"profile": profile, "physical": {key: value.as_dict() for key, value in physical.items()}, **namespaces}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    identity = f"default:{profile}" if not physical and not any(namespaces.values()) else "calibration-v1:" + encoded
    return ResolvedCalibration("xbox_one_s", profile, identity, motion_revision, physical, namespaces["signal_policy"], namespaces["spawn"], namespaces["backend_options"], chain)


def export_resolved(calibration: ResolvedCalibration, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(asdict(calibration), indent=2) + "\n", encoding="utf-8")


def resolved_from_dict(raw: Mapping[str, object]) -> ResolvedCalibration:
    """Restore a prepared configuration identity without consulting the environment."""
    physical = {key: Parameter.from_dict(value) for key, value in raw["physical"].items()}
    chain = {key: tuple(Evidence(**{**item, "assumptions": tuple(item.get("assumptions", ()))}) for item in values)
             for key, values in raw["source_chain"].items()}
    return ResolvedCalibration(raw["asset_id"], raw["profile"], raw["configuration_id"], raw["motion_revision"],
                               physical, raw["signal_policy"], raw["spawn"], raw["backend_options"], chain)
