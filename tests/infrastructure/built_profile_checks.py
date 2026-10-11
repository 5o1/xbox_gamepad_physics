"""Build-time property checks for generated RoboTwin profiles.

These rules used to run on every load. Generated profiles come from the
generators, so the asset tests check them once on the built output instead.
"""

from __future__ import annotations

import math
from pathlib import Path
import xml.etree.ElementTree as ET


def _numbers(element: ET.Element, attribute: str, length: int, context: str) -> tuple[float, ...]:
    raw = element.get(attribute)
    if not isinstance(raw, str):
        raise AssertionError(f"{context} needs attribute {attribute!r}")
    values = tuple(float(value) for value in raw.split())
    if len(values) != length or not all(math.isfinite(value) for value in values):
        raise AssertionError(f"{context}.{attribute} must contain {length} finite numbers")
    return values


def _number(element: ET.Element, attribute: str, context: str) -> float:
    return _numbers(element, attribute, 1, context)[0]


def check_explicit_urdf_physics(urdf_path: Path, *, require_moving_meshes=False) -> set[str]:
    """Reject URDFs that would let SAPIEN invent physical defaults; return active joint names."""

    root = ET.parse(urdf_path).getroot()
    if root.tag != "robot":
        raise AssertionError("URDF root element must be <robot>")
    links = root.findall("link")
    if not links:
        raise AssertionError("URDF contains no links")
    link_names: set[str] = set()
    collisions = 0
    for link in links:
        name = link.get("name")
        if not name or name in link_names:
            raise AssertionError(f"invalid or duplicate URDF link name {name!r}")
        link_names.add(name)
        inertial = link.find("inertial")
        parts = [inertial.find(tag) if inertial is not None else None for tag in ("origin", "mass", "inertia")]
        if inertial is None or any(part is None for part in parts):
            raise AssertionError(f"URDF link {name!r} needs explicit inertial origin, mass, and inertia")
        origin, mass, inertia = parts
        _numbers(origin, "xyz", 3, f"link {name!r} inertial origin")
        _numbers(origin, "rpy", 3, f"link {name!r} inertial origin")
        if _number(mass, "value", f"link {name!r} mass") <= 0:
            raise AssertionError(f"URDF link {name!r} mass must be positive")
        ixx, ixy, ixz, iyy, iyz, izz = (
            _number(inertia, key, f"link {name!r} inertia") for key in ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")
        )
        determinant = ixx * (iyy * izz - iyz * iyz) - ixy * (ixy * izz - iyz * ixz) + ixz * (ixy * iyz - iyy * ixz)
        if ixx <= 0 or ixx * iyy - ixy * ixy <= 0 or determinant <= 0:
            raise AssertionError(f"URDF link {name!r} inertia tensor must be positive definite")
        collisions += len(link.findall("collision"))
        for mesh in link.findall("collision/geometry/mesh"):
            if not (urdf_path.parent / mesh.get("filename", "")).is_file():
                raise AssertionError(f"link {name!r} collision mesh is missing")
    if collisions == 0:
        raise AssertionError("URDF contains no collision geometry")

    active: set[str] = set()
    frame_parents = {joint.find("parent").get("link") for joint in root.findall("joint")}
    for joint in root.findall("joint"):
        name, kind = joint.get("name"), joint.get("type")
        if not name:
            raise AssertionError("every URDF joint needs a non-empty name")
        for tag in ("parent", "child"):
            element = joint.find(tag)
            if element is None or element.get("link") not in link_names:
                raise AssertionError(f"joint {name!r} has an invalid {tag} link")
        origin = joint.find("origin")
        if origin is None:
            raise AssertionError(f"joint {name!r} needs an explicit origin")
        _numbers(origin, "xyz", 3, f"joint {name!r} origin")
        _numbers(origin, "rpy", 3, f"joint {name!r} origin")
        if kind == "fixed":
            continue
        if kind not in {"revolute", "continuous", "prismatic"} or name in active:
            raise AssertionError(f"joint {name!r} has an unsupported type or a duplicate name")
        active.add(name)
        if require_moving_meshes:
            child = joint.find("child").get("link")
            # Intermediate motion frames carry no control geometry.
            if child not in frame_parents:
                link = next(link for link in links if link.get("name") == child)
                if not link.findall("collision/geometry/mesh"):
                    raise AssertionError(f"moving control link {child!r} needs at least one mesh collision")
        axis, limit = joint.find("axis"), joint.find("limit")
        if axis is None or math.dist(_numbers(axis, "xyz", 3, f"joint {name!r} axis"), (0, 0, 0)) <= 1e-12:
            raise AssertionError(f"joint {name!r} needs an explicit non-zero axis")
        if limit is None:
            raise AssertionError(f"joint {name!r} needs explicit limits")
        if _number(limit, "effort", f"joint {name!r} limit") <= 0 or _number(limit, "velocity", f"joint {name!r} limit") <= 0:
            raise AssertionError(f"joint {name!r} effort and velocity limits must be positive")
        if kind != "continuous" and not _number(limit, "lower", name) < _number(limit, "upper", name):
            raise AssertionError(f"joint {name!r} lower limit must be smaller than upper")
    return active


def _finite(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AssertionError(f"{context} must be a finite number, got {value!r}")
    return float(value)


def check_manifest_ranges(manifest: dict) -> None:
    """Numeric types and value ranges the generators guarantee for joints and contact material."""

    for item in manifest["joint_dynamics"]:
        values = {
            key: _finite(item[key], f"joint {item['name']!r} {key}")
            for key in ("stiffness", "damping", "force_limit", "friction", "target")
        }
        if min(values["stiffness"], values["damping"], values["friction"]) < 0 or values["force_limit"] <= 0:
            raise AssertionError(f"joint {item['name']!r} dynamics are outside valid ranges")
    contact = {
        key: _finite(manifest["contact_material"][key], f"contact_material {key}")
        for key in ("static_friction", "dynamic_friction", "restitution", "contact_offset_m", "rest_offset_m")
    }
    if (
        contact["static_friction"] < 0
        or contact["dynamic_friction"] < 0
        or not 0 <= contact["restitution"] <= 1
        or not 0 <= contact["rest_offset_m"] < contact["contact_offset_m"]
    ):
        raise AssertionError("contact_material values are outside valid ranges")
