"""Evidence-bound Xbox physical specification; no implicit numeric defaults.

The schema separates logical gamepad effects from physical mechanism topology.
An unresolved control therefore has an empty joint list instead of a fabricated
single joint. Reference component values remain separate from target values.
"""

import argparse
import ast
import copy
import hashlib
import json
import math
import numbers
import os
from pathlib import Path, PurePosixPath
import re


ROOT = Path(__file__).resolve().parents[1]
ASSET_REGISTRY_PATH = ROOT / "assets/asset_index.json"
SCHEMA_VERSION = 2
REPORT_SCHEMA_VERSION = 2
ASSET_REGISTRY_SPEC_PATH = "assets/asset_index.json"
ASSET_ID_COLLECTIONS = ("candidates", "derived_variants")

BODY_FIELDS = (
    "body_role",
    "visual_geometry",
    "mass",
    "center_of_mass",
    "inertia",
    "collision_geometry",
    "contact_friction",
    "contact_restitution",
)
JOINT_FIELDS = (
    "parent_body",
    "child_body",
    "joint_type",
    "actuation_mode",
    "joint_origin",
    "joint_axis",
    "joint_limits",
    "actuator_effort_limit",
    "actuator_velocity_limit",
    "restoring_curve",
    "damping",
    "joint_friction",
    "input_mapping",
)
UNITS = {
    "body_role": None,
    "visual_geometry": None,
    "mass": "kg",
    "center_of_mass": "m",
    "inertia": "kg*m^2",
    "collision_geometry": None,
    "contact_friction": "1",
    "contact_restitution": "1",
}
BODY_ROLES = {"physical", "virtual_frame"}
BODY_PROPERTY_FIELDS = tuple(field for field in BODY_FIELDS if field != "body_role")

CONTROLS = (
    "shell",
    "a",
    "b",
    "x",
    "y",
    "left_stick",
    "right_stick",
    "dpad",
    "left_shoulder",
    "right_shoulder",
    "left_trigger",
    "right_trigger",
    "view",
    "menu",
    "guide",
    "pair",
)

# Tensor index is this project's explicit concatenation of the W3C standard
# axes then buttons. It is not presented as a W3C tensor representation.
CHANNEL_DEFINITIONS = (
    ("lx", "axis", 0, 0, (-1, 1)),
    ("ly", "axis", 1, 1, (-1, 1)),
    ("rx", "axis", 2, 2, (-1, 1)),
    ("ry", "axis", 3, 3, (-1, 1)),
    ("a", "button", 4, 0, (0, 1)),
    ("b", "button", 5, 1, (0, 1)),
    ("x", "button", 6, 2, (0, 1)),
    ("y", "button", 7, 3, (0, 1)),
    ("left_shoulder", "button", 8, 4, (0, 1)),
    ("right_shoulder", "button", 9, 5, (0, 1)),
    ("left_trigger", "button", 10, 6, (0, 1)),
    ("right_trigger", "button", 11, 7, (0, 1)),
    ("view", "button", 12, 8, (0, 1)),
    ("menu", "button", 13, 9, (0, 1)),
    ("left_stick_click", "button", 14, 10, (0, 1)),
    ("right_stick_click", "button", 15, 11, (0, 1)),
    ("dpad_up", "button", 16, 12, (0, 1)),
    ("dpad_down", "button", 17, 13, (0, 1)),
    ("dpad_left", "button", 18, 14, (0, 1)),
    ("dpad_right", "button", 19, 15, (0, 1)),
    ("guide", "button", 20, 16, (0, 1)),
)
CANONICAL_CHANNELS = tuple(item[0] for item in CHANNEL_DEFINITIONS)
CHANNEL_RANGES = {item[0]: item[4] for item in CHANNEL_DEFINITIONS}
ANALOG_CHANNELS = {"lx", "ly", "rx", "ry", "left_trigger", "right_trigger"}
DIGITAL_CHANNELS = set(CANONICAL_CHANNELS) - ANALOG_CHANNELS

CONTROL_EFFECTS = {
    "shell": (),
    "a": ("a",),
    "b": ("b",),
    "x": ("x",),
    "y": ("y",),
    "left_stick": ("lx", "ly", "left_stick_click"),
    "right_stick": ("rx", "ry", "right_stick_click"),
    "dpad": ("dpad_up", "dpad_down", "dpad_left", "dpad_right"),
    "left_shoulder": ("left_shoulder",),
    "right_shoulder": ("right_shoulder",),
    "left_trigger": ("left_trigger",),
    "right_trigger": ("right_trigger",),
    "view": ("view",),
    "menu": ("menu",),
    "guide": ("guide",),
    # Pair/Bind/Connect changes connectivity state. It is a physical control,
    # but it is absent from the W3C Standard Gamepad's 17 buttons + 4 axes.
    "pair": (),
}

JOINT_TYPES = {"continuous", "prismatic", "revolute"}
JOINT_UNITS = {
    "revolute": {
        "parent_body": None,
        "child_body": None,
        "joint_type": None,
        "actuation_mode": None,
        "joint_origin": "m,rad",
        "joint_axis": "1",
        "joint_limits": "rad",
        "actuator_effort_limit": "N*m",
        "actuator_velocity_limit": "rad/s",
        "restoring_curve": "rad,N*m",
        "damping": "N*m*s/rad",
        "joint_friction": "N*m",
        "input_mapping": "rad->1",
    },
    "continuous": {
        "parent_body": None,
        "child_body": None,
        "joint_type": None,
        "actuation_mode": None,
        "joint_origin": "m,rad",
        "joint_axis": "1",
        "joint_limits": "rad",
        "actuator_effort_limit": "N*m",
        "actuator_velocity_limit": "rad/s",
        "restoring_curve": "rad,N*m",
        "damping": "N*m*s/rad",
        "joint_friction": "N*m",
        "input_mapping": "rad->1",
    },
    "prismatic": {
        "parent_body": None,
        "child_body": None,
        "joint_type": None,
        "actuation_mode": None,
        "joint_origin": "m,rad",
        "joint_axis": "1",
        "joint_limits": "m",
        "actuator_effort_limit": "N",
        "actuator_velocity_limit": "m/s",
        "restoring_curve": "m,N",
        "damping": "N*s/m",
        "joint_friction": "N",
        "input_mapping": "m->1",
    },
}
COLLISION_TYPES = {"box", "capsule", "convex_mesh", "cylinder", "mesh", "sphere"}
PHYSX_COMBINE_MODES = {"average", "max", "min", "multiply"}
UINT32_MAX = 2 ** 32 - 1
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
JOINT_ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")


def _number(value):
    """Return true only for finite JSON-style numbers (never bool)."""
    if not isinstance(value, numbers.Real) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _finite_tree(value):
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return _number(value)
    if isinstance(value, (list, tuple)):
        return all(_finite_tree(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite_tree(item) for key, item in value.items())
    return True


def _vector(value, length):
    return (
        isinstance(value, (list, tuple))
        and len(value) == length
        and all(_number(item) for item in value)
    )


def _positive_number(value, upper=None, allow_zero=False):
    if not _number(value):
        return False
    if value < 0 or (not allow_zero and value == 0):
        return False
    return upper is None or value <= upper


def _safe_relative_asset_path(value):
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and bool(path.parts)
        and value != "."
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _body_pose_valid(value, frame, unit):
    return (
        frame == "body"
        and unit == "m,rad"
        and isinstance(value, dict)
        and set(value) == {"xyz", "rpy"}
        and _vector(value["xyz"], 3)
        and _vector(value["rpy"], 3)
    )


def _collision_filter_errors(value):
    """Validate SAPIEN's four PhysX filter words without a lossy group/mask alias."""
    expected = {
        "backend", "word0_contact_type", "word1_contact_affinity",
        "word2_ignore_bits", "word3_id", "semantics",
    }
    if not isinstance(value, dict) or set(value) != expected:
        return ["must contain the exact SAPIEN/PhysX four-word filter fields"]
    errors = []
    if value.get("backend") != "sapien_physx_v3":
        errors.append("backend must be sapien_physx_v3")
    if value.get("semantics") != "sapien_set_collision_groups_four_word_rule":
        errors.append("semantics must name the SAPIEN four-word collision rule")
    for key in (
        "word0_contact_type", "word1_contact_affinity", "word2_ignore_bits",
        "word3_id",
    ):
        upper = 0xFFFF if key == "word3_id" else UINT32_MAX
        if type(value.get(key)) is not int or not 0 <= value[key] <= upper:
            errors.append(
                f"{key} must be {'a uint16-effective id' if key == 'word3_id' else 'uint32'}"
            )
    return errors


def _sapien_filters_allow(first, second):
    """Return SAPIEN's documented four-word pair-filter result."""
    try:
        contact = (
            (first["word0_contact_type"] & second["word1_contact_affinity"]) != 0
            or (first["word1_contact_affinity"] & second["word0_contact_type"]) != 0
        )
        ignored = (
            (first["word2_ignore_bits"] & second["word2_ignore_bits"]) != 0
            and (first["word3_id"] & 0xFFFF) == (second["word3_id"] & 0xFFFF)
        )
        return contact and not ignored
    except (KeyError, TypeError):
        return False


def _triangle_mesh_backend_errors(value):
    expected = {
        "engine", "simulation_role", "actor_kind", "actor_mobility", "cooking",
        "gpu_dynamics", "sdf_artifact",
    }
    if not isinstance(value, dict) or set(value) != expected:
        return ["triangle mesh must declare the exact PhysX backend-shape policy"]
    errors = []
    if value.get("engine") != "physx_5":
        errors.append("engine must be physx_5")
    role = value.get("simulation_role")
    actor_kind = value.get("actor_kind")
    mobility = value.get("actor_mobility")
    if role not in {"simulation_and_query", "query_only"}:
        errors.append("simulation_role must be simulation_and_query or query_only")
    if mobility not in {"static", "kinematic", "dynamic"}:
        errors.append("actor_mobility must be static, kinematic or dynamic")
    kind_mobility = {
        "rigid_static": "static",
        "rigid_kinematic": "kinematic",
        "rigid_dynamic": "dynamic",
        "articulation_link_nonkinematic": "dynamic",
    }
    if actor_kind not in kind_mobility:
        errors.append(
            "actor_kind must distinguish rigid static/kinematic/dynamic actors from "
            "a non-kinematic articulation link"
        )
    elif mobility != kind_mobility[actor_kind]:
        errors.append("actor_mobility contradicts actor_kind")
    sdf = value.get("sdf_artifact")
    sdf_valid = (
        isinstance(sdf, dict)
        and set(sdf) == {"file", "sha256"}
        and _safe_relative_asset_path(sdf.get("file"))
        and isinstance(sdf.get("sha256"), str)
        and SHA256_RE.fullmatch(sdf["sha256"])
    )
    dynamic_simulation = (
        role == "simulation_and_query"
        and actor_kind in {"rigid_dynamic", "articulation_link_nonkinematic"}
    )
    if dynamic_simulation:
        if value.get("cooking") != "triangle_mesh_sdf":
            errors.append("non-kinematic dynamic triangle mesh requires triangle_mesh_sdf cooking")
        if value.get("gpu_dynamics") is not True:
            errors.append("non-kinematic dynamic triangle mesh requires GPU dynamics")
        if not sdf_valid:
            errors.append("non-kinematic dynamic triangle mesh requires a safe SHA-bound SDF artifact")
    else:
        if value.get("cooking") != "triangle_mesh":
            errors.append("static, kinematic and query-only triangle meshes use ordinary triangle_mesh cooking")
        if value.get("gpu_dynamics") is not False:
            errors.append("GPU dynamics must be false when no dynamic SDF simulation shape is declared")
        if sdf is not None:
            errors.append("ordinary static/kinematic/query-only triangle mesh must not claim an SDF artifact")
    return errors


def _convex_mesh_backend_errors(value):
    expected = {
        "engine", "simulation_role", "actor_kind", "actor_mobility", "cooking",
        "gpu_dynamics", "sdf_artifact",
    }
    if not isinstance(value, dict) or set(value) != expected:
        return ["convex mesh must declare the exact PhysX backend-shape policy"]
    errors = []
    if value.get("engine") != "physx_5":
        errors.append("engine must be physx_5")
    if value.get("simulation_role") not in {"simulation_and_query", "query_only"}:
        errors.append("simulation_role must be simulation_and_query or query_only")
    if value.get("actor_mobility") not in {"static", "kinematic", "dynamic"}:
        errors.append("actor_mobility must be static, kinematic or dynamic")
    kind_mobility = {
        "rigid_static": "static",
        "rigid_kinematic": "kinematic",
        "rigid_dynamic": "dynamic",
        "articulation_link_nonkinematic": "dynamic",
    }
    actor_kind = value.get("actor_kind")
    if actor_kind not in kind_mobility:
        errors.append(
            "actor_kind must distinguish rigid static/kinematic/dynamic actors from "
            "a non-kinematic articulation link"
        )
    elif value.get("actor_mobility") != kind_mobility[actor_kind]:
        errors.append("actor_mobility contradicts actor_kind")
    if value.get("cooking") != "convex_hull":
        errors.append("convex mesh cooking must be convex_hull")
    if value.get("gpu_dynamics") is not False:
        errors.append("convex_hull declaration does not use the triangle-mesh GPU-SDF gate")
    if value.get("sdf_artifact") is not None:
        errors.append("convex_hull must not claim a triangle-mesh SDF artifact")
    return errors


def _visual_errors(value):
    meshes = value if isinstance(value, list) else [value]
    if not meshes or any(not isinstance(mesh, dict) for mesh in meshes):
        return ["must be a visual mesh object or non-empty list of visual mesh objects"]
    errors = []
    expected_keys = {
        "type", "candidate_id", "artifact_id", "object_id", "frame", "pose",
        "pose_unit", "file", "sha256",
        "meters_per_native_unit", "meters_per_native_unit_unit", "materials",
    }
    for index, mesh in enumerate(meshes):
        prefix = f"visual[{index}]"
        if set(mesh) != expected_keys or mesh.get("type") != "mesh":
            errors.append(f"{prefix}: visual mesh fields changed")
        if not isinstance(mesh.get("candidate_id"), str) or not JOINT_ID_RE.fullmatch(
            mesh["candidate_id"]
        ):
            errors.append(f"{prefix}.candidate_id must be a stable lowercase asset id")
        if not isinstance(mesh.get("artifact_id"), str) or not JOINT_ID_RE.fullmatch(
            mesh["artifact_id"]
        ):
            errors.append(f"{prefix}.artifact_id must be a stable lowercase artifact id")
        if (
            not isinstance(mesh.get("object_id"), str)
            or not mesh["object_id"].strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in mesh["object_id"])
        ):
            errors.append(f"{prefix}.object_id must be a non-empty manifest object id")
        if not _body_pose_valid(mesh.get("pose"), mesh.get("frame"), mesh.get("pose_unit")):
            errors.append(f"{prefix} must have a finite body-relative pose with pose_unit 'm,rad'")
        if not _safe_relative_asset_path(mesh.get("file")):
            errors.append(f"{prefix}.file must be a normalized safe relative POSIX path")
        if not isinstance(mesh.get("sha256"), str) or not SHA256_RE.fullmatch(mesh["sha256"]):
            errors.append(f"{prefix}.sha256 must be 64 lowercase hexadecimal characters")
        if mesh.get("meters_per_native_unit_unit") != "m/native_unit" or not (
            _vector(mesh.get("meters_per_native_unit"), 3)
            and all(component > 0 for component in mesh["meters_per_native_unit"])
        ):
            errors.append(
                f"{prefix}.meters_per_native_unit must be three positive finite values "
                "with unit 'm/native_unit'"
            )
        materials = mesh.get("materials")
        if not isinstance(materials, dict) or set(materials) != {"mode", "files"}:
            errors.append(f"{prefix}.materials must contain mode and files")
            continue
        mode, files = materials.get("mode"), materials.get("files")
        if mode not in {"embedded", "external", "none"} or not isinstance(files, list):
            errors.append(f"{prefix}.materials has an invalid mode/files representation")
            continue
        if (mode == "external") != bool(files):
            errors.append(f"{prefix}.materials external mode requires files; other modes require none")
        for file_index, material_file in enumerate(files):
            if (
                not isinstance(material_file, dict)
                or set(material_file) != {"file", "sha256"}
                or not _safe_relative_asset_path(material_file.get("file"))
                or not isinstance(material_file.get("sha256"), str)
                or not SHA256_RE.fullmatch(material_file["sha256"])
            ):
                errors.append(f"{prefix}.materials.files[{file_index}] must bind a safe path and SHA256")
    return errors


def _collision_errors(value):
    colliders = value if isinstance(value, list) else [value]
    if not colliders or any(not isinstance(item, dict) for item in colliders):
        return ["must be a collider object or non-empty list of collider objects"]
    errors = []
    for index, collider in enumerate(colliders):
        kind = collider.get("type")
        prefix = f"collider[{index}]"
        common_keys = {
            "type", "frame", "pose", "pose_unit", "collision_filter",
            "contact_offset", "rest_offset", "offset_unit",
        }
        pose_valid = _body_pose_valid(
            collider.get("pose"), collider.get("frame"), collider.get("pose_unit")
        )
        if not pose_valid:
            errors.append(
                f"{prefix} must have a finite body-relative pose with pose_unit 'm,rad'"
            )
        errors.extend(
            f"{prefix}.collision_filter: {detail}"
            for detail in _collision_filter_errors(collider.get("collision_filter"))
        )
        if (
            collider.get("offset_unit") != "m"
            or not _positive_number(collider.get("contact_offset"), allow_zero=True)
            or not _number(collider.get("rest_offset"))
            or (
                _number(collider.get("contact_offset"))
                and _number(collider.get("rest_offset"))
                and collider["rest_offset"] >= collider["contact_offset"]
            )
        ):
            errors.append(
                f"{prefix}: contact_offset must be finite and non-negative; rest_offset "
                "must be finite and strictly less than contact_offset"
            )
        if kind not in COLLISION_TYPES:
            errors.append(f"{prefix}.type must be one of {sorted(COLLISION_TYPES)}")
        elif kind == "box":
            if set(collider) != common_keys | {"size", "size_unit", "size_semantics"}:
                errors.append(f"{prefix}: box fields changed")
            if collider.get("size_unit") != "m" or collider.get("size_semantics") != "full_extents" or not (
                _vector(collider.get("size"), 3)
                and all(component > 0 for component in collider["size"])
            ):
                errors.append(f"{prefix}.size must be three positive finite metres")
        elif kind == "sphere":
            if set(collider) != common_keys | {"radius", "radius_unit"}:
                errors.append(f"{prefix}: sphere fields changed")
            if collider.get("radius_unit") != "m" or not _positive_number(
                collider.get("radius")
            ):
                errors.append(f"{prefix}.radius must be positive finite metres")
        elif kind in {"cylinder", "capsule"}:
            if set(collider) != common_keys | {
                "radius", "height", "length_unit", "axis", "height_semantics",
            }:
                errors.append(f"{prefix}: {kind} fields changed")
            expected_semantics = (
                "full_length" if kind == "cylinder"
                else "cylindrical_section_excluding_hemispheres"
            )
            if (
                collider.get("length_unit") != "m"
                or collider.get("axis") not in {"x", "y", "z"}
                or collider.get("height_semantics") != expected_semantics
                or not (
                _positive_number(collider.get("radius"))
                and _positive_number(collider.get("height"))
                )
            ):
                errors.append(f"{prefix} radius and height must be positive finite metres")
        elif kind in {"mesh", "convex_mesh"}:
            mesh_keys = {
                "file", "sha256",
                "meters_per_native_unit", "meters_per_native_unit_unit",
            }
            mesh_keys.add("backend_shape")
            if set(collider) != common_keys | mesh_keys:
                errors.append(f"{prefix}: {kind} fields changed")
            if not _safe_relative_asset_path(collider.get("file")):
                errors.append(f"{prefix}.file must be a normalized safe relative POSIX path")
            if not isinstance(collider.get("sha256"), str) or not SHA256_RE.fullmatch(
                collider["sha256"]
            ):
                errors.append(f"{prefix}.sha256 must be 64 lowercase hexadecimal characters")
            if collider.get("meters_per_native_unit_unit") != "m/native_unit" or not (
                _vector(collider.get("meters_per_native_unit"), 3)
                and all(
                    component > 0
                    for component in collider["meters_per_native_unit"]
                )
            ):
                errors.append(
                    f"{prefix}.meters_per_native_unit must be three positive finite values "
                    "with unit 'm/native_unit'"
                )
            if kind == "mesh":
                errors.extend(
                    f"{prefix}.backend_shape: {detail}"
                    for detail in _triangle_mesh_backend_errors(collider.get("backend_shape"))
                )
            else:
                errors.extend(
                    f"{prefix}.backend_shape: {detail}"
                    for detail in _convex_mesh_backend_errors(collider.get("backend_shape"))
                )
    return errors


def _inertia_errors(value):
    if not isinstance(value, dict) or set(value) != {"matrix", "about", "expressed_in"}:
        return ["must contain matrix, about and expressed_in"]
    if value.get("about") != "center_of_mass" or value.get("expressed_in") != "body_frame":
        return ["must be about center_of_mass and expressed in body_frame"]
    value = value.get("matrix")
    if not (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(_vector(row, 3) for row in value)
    ):
        return ["must be a finite 3x3 inertia tensor"]
    matrix = [[float(component) for component in row] for row in value]
    scale = max(abs(component) for row in matrix for component in row)
    tolerance = 1e-9 * scale
    if any(abs(matrix[i][j] - matrix[j][i]) > tolerance for i in range(3) for j in range(3)):
        return ["inertia tensor must be symmetric"]
    a, b, c = matrix[0]
    _, d, e = matrix[1]
    _, _, f = matrix[2]
    determinant = a * (d * f - e * e) - b * (b * f - c * e) + c * (b * e - c * d)
    if not (a > 0 and a * d - b * b > 0 and determinant > 0):
        return ["inertia tensor must be positive definite"]
    off_diagonal_square = b * b + c * c + e * e
    if off_diagonal_square == 0:
        principal = sorted((a, d, f))
    else:
        mean = (a + d + f) / 3
        spread = math.sqrt(
            ((a - mean) ** 2 + (d - mean) ** 2 + (f - mean) ** 2 + 2 * off_diagonal_square)
            / 6
        )
        normalized = [[(matrix[i][j] - (mean if i == j else 0)) / spread for j in range(3)] for i in range(3)]
        normalized_det = (
            normalized[0][0] * (normalized[1][1] * normalized[2][2] - normalized[1][2] ** 2)
            - normalized[0][1] * (normalized[0][1] * normalized[2][2] - normalized[0][2] * normalized[1][2])
            + normalized[0][2] * (normalized[0][1] * normalized[1][2] - normalized[0][2] * normalized[1][1])
        )
        angle = math.acos(max(-1.0, min(1.0, normalized_det / 2))) / 3
        first = mean + 2 * spread * math.cos(angle)
        third = mean + 2 * spread * math.cos(angle + 2 * math.pi / 3)
        second = 3 * mean - first - third
        principal = sorted((first, second, third))
    if principal[2] > principal[0] + principal[1] + 1e-9 * principal[2]:
        return ["principal moments violate the rigid-body triangle inequality"]
    return []


def _analog_mapping_errors(value, *, physical_only=False):
    expected_keys = {
        "model", "effects", "interpolation", "outside_domain", "inverse_policy",
        "neutral_coordinate",
    }
    if physical_only:
        return ["physical-only controls must use digital_hysteresis with a physical event"]
    if not isinstance(value, dict) or set(value) != expected_keys:
        return [f"analog_monotone mapping must contain exactly {sorted(expected_keys)}"]
    errors = []
    if value.get("model") != "analog_monotone":
        errors.append("model must be analog_monotone")
    effects = value.get("effects")
    if not isinstance(effects, list) or not effects:
        return [*errors, "analog_monotone requires at least one effect"]
    if value.get("interpolation") != "piecewise_linear":
        errors.append("interpolation must be piecewise_linear")
    if value.get("outside_domain") != "reject":
        errors.append("outside_domain must be reject; clamp/extrapolation is not implicit")
    if value.get("inverse_policy") != "unique_monotone_effect_tuple":
        errors.append("inverse_policy must be unique_monotone_effect_tuple")
    if not _number(value.get("neutral_coordinate")):
        errors.append("neutral_coordinate must be finite")
    seen = set()
    shared_coordinates = None
    signals_by_effect = []
    for index, effect in enumerate(effects):
        prefix = f"effect[{index}]"
        if not isinstance(effect, dict) or set(effect) != {"channel", "curve", "direction"}:
            errors.append(f"{prefix} must contain exactly channel, curve and direction")
            continue
        channel = effect.get("channel")
        if channel not in CANONICAL_CHANNELS:
            errors.append(f"{prefix}.channel is not a canonical 21-channel name")
            continue
        if channel not in ANALOG_CHANNELS:
            errors.append(f"{prefix}.channel is digital on the target and requires digital_hysteresis")
        if channel in seen:
            errors.append(f"{prefix}.channel is duplicated")
        seen.add(channel)
        curve = effect.get("curve")
        if not isinstance(curve, list) or len(curve) < 2 or not all(_vector(point, 2) for point in curve):
            errors.append(f"{prefix}.curve must have at least two finite [coordinate, signal] points")
            continue
        if not all(curve[i][0] < curve[i + 1][0] for i in range(len(curve) - 1)):
            errors.append(f"{prefix}.curve coordinates must be strictly increasing")
        lower, upper = CHANNEL_RANGES[channel]
        if any(point[1] < lower or point[1] > upper for point in curve):
            errors.append(f"{prefix}.curve signals must remain in [{lower}, {upper}]")
        coordinates = [point[0] for point in curve]
        signals = [point[1] for point in curve]
        if shared_coordinates is None:
            shared_coordinates = coordinates
        elif coordinates != shared_coordinates:
            errors.append(f"{prefix}.curve must share coordinate knots with every effect")
        direction = effect.get("direction")
        differences = [signals[i + 1] - signals[i] for i in range(len(signals) - 1)]
        direction_valid = {
            "strictly_increasing": all(delta > 0 for delta in differences),
            "strictly_decreasing": all(delta < 0 for delta in differences),
            "nondecreasing": all(delta >= 0 for delta in differences) and any(delta > 0 for delta in differences),
            "nonincreasing": all(delta <= 0 for delta in differences) and any(delta < 0 for delta in differences),
        }
        if direction not in direction_valid or not direction_valid[direction]:
            errors.append(f"{prefix}.direction does not match its monotone signal curve")
        if len(effects) == 1 and direction not in {"strictly_increasing", "strictly_decreasing"}:
            errors.append(f"{prefix}: a single-effect inverse must be strictly monotone")
        if min(signals) != lower or max(signals) != upper:
            errors.append(f"{prefix}.curve must cover the full canonical signal range [{lower}, {upper}]")
        neutral_coordinate = value.get("neutral_coordinate")
        neutral_points = [
            point for point in curve
            if _number(neutral_coordinate)
            and math.isclose(point[0], neutral_coordinate, rel_tol=0.0, abs_tol=1e-12)
        ]
        if len(neutral_points) != 1 or not math.isclose(
            neutral_points[0][1], 0.0, rel_tol=0.0, abs_tol=1e-12
        ):
            errors.append(f"{prefix}.curve must contain [neutral_coordinate, 0]")
        signals_by_effect.append(signals)
    if shared_coordinates is not None and len(signals_by_effect) == len(effects) and len(effects) > 1:
        for interval in range(len(shared_coordinates) - 1):
            if all(signals[interval] == signals[interval + 1] for signals in signals_by_effect):
                errors.append(
                    "effect tuple is not invertible: every channel is flat on one coordinate interval"
                )
    return errors


def _digital_condition_satisfied(effect, coordinate, active):
    side = effect["pressed_side"]
    threshold = effect["press_threshold"] if active else effect["release_threshold"]
    return coordinate >= threshold if (side == "positive") == active else coordinate <= threshold


def _digital_mapping_errors(value, *, physical_only=False):
    expected_keys = {
        "model", "output_kind", "effects", "physical_event", "coordinate_domain",
        "outside_domain", "initial_state", "state_semantics", "inverse_policy",
        "inverse_representatives", "neutral_coordinate",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        return [f"digital_hysteresis mapping must contain exactly {sorted(expected_keys)}"]
    errors = []
    if value.get("model") != "digital_hysteresis":
        errors.append("model must be digital_hysteresis")
    domain = value.get("coordinate_domain")
    if not _vector(domain, 2) or domain[0] >= domain[1]:
        errors.append("coordinate_domain must be finite [lower, upper] with lower < upper")
        domain = None
    if value.get("outside_domain") != "reject":
        errors.append("outside_domain must be reject")
    if value.get("state_semantics") != "schmitt_trigger_retains_state_between_thresholds":
        errors.append("state_semantics must explicitly define Schmitt-trigger retention")
    if value.get("inverse_policy") != "representative_coordinates_not_unique_inverse":
        errors.append("inverse_policy must state that representatives are not a unique inverse")
    neutral = value.get("neutral_coordinate")
    if not _number(neutral) or (domain is not None and not domain[0] <= neutral <= domain[1]):
        errors.append("neutral_coordinate must be finite and inside coordinate_domain")

    effects = value.get("effects")
    event = value.get("physical_event")
    if physical_only:
        if value.get("output_kind") != "physical_event" or effects != []:
            errors.append("physical-only mapping requires output_kind physical_event and no tensor effects")
        if not isinstance(event, dict) or set(event) != {
            "name", "pressed_side", "press_threshold", "release_threshold"
        } or event.get("name") != "pair_bind_connect":
            errors.append("physical_event must define the Pair/Bind/Connect switch thresholds")
            transition_records = []
        else:
            transition_records = [event]
    else:
        if value.get("output_kind") != "standard_channels" or event is not None:
            errors.append("standard digital mapping requires output_kind standard_channels and no physical_event")
        if not isinstance(effects, list) or not effects:
            errors.append("standard digital mapping requires at least one effect")
            effects = []
        transition_records = effects

    seen = set()
    for index, effect in enumerate(transition_records):
        prefix = "physical_event" if physical_only else f"effect[{index}]"
        expected_effect_keys = (
            {"name", "pressed_side", "press_threshold", "release_threshold"}
            if physical_only
            else {"channel", "pressed_side", "press_threshold", "release_threshold"}
        )
        if not isinstance(effect, dict) or set(effect) != expected_effect_keys:
            errors.append(f"{prefix}: transition fields changed")
            continue
        if not physical_only:
            channel = effect.get("channel")
            if channel not in CANONICAL_CHANNELS:
                errors.append(f"{prefix}.channel is not a canonical 21-channel name")
            elif channel not in DIGITAL_CHANNELS:
                errors.append(f"{prefix}.channel is analog and requires analog_monotone")
            if channel in seen:
                errors.append(f"{prefix}.channel is duplicated")
            seen.add(channel)
        side = effect.get("pressed_side")
        press, release = effect.get("press_threshold"), effect.get("release_threshold")
        if side not in {"positive", "negative"} or not _number(press) or not _number(release):
            errors.append(f"{prefix}: pressed_side and finite thresholds are required")
        elif domain is not None:
            valid_order = (
                domain[0] <= release < press <= domain[1]
                if side == "positive"
                else domain[0] <= press < release <= domain[1]
            )
            if not valid_order:
                errors.append(f"{prefix}: press/release thresholds have an invalid order for {side} q")

    output_count = 1 if physical_only else len(effects)
    initial = value.get("initial_state")
    if initial != [0] * output_count:
        errors.append("initial_state must explicitly set every digital output inactive (0)")
    representatives = value.get("inverse_representatives")
    if not isinstance(representatives, list) or not representatives:
        errors.append("inverse_representatives must be a non-empty list")
        representatives = []
    states = set()
    neutral_records = []
    for index, representative in enumerate(representatives):
        prefix = f"inverse_representatives[{index}]"
        if not isinstance(representative, dict) or set(representative) != {"output_state", "coordinate"}:
            errors.append(f"{prefix}: fields changed")
            continue
        state = representative.get("output_state")
        coordinate = representative.get("coordinate")
        if (
            not isinstance(state, list)
            or len(state) != output_count
            or any(type(item) is not int or item not in {0, 1} for item in state)
        ):
            errors.append(f"{prefix}.output_state: must be {output_count} binary integers")
            continue
        state_key = tuple(state)
        if state_key in states:
            errors.append(f"{prefix}.output_state: duplicate")
        states.add(state_key)
        if not _number(coordinate) or (domain is not None and not domain[0] <= coordinate <= domain[1]):
            errors.append(f"{prefix}.coordinate: must be finite and inside coordinate_domain")
            continue
        if state_key == tuple([0] * output_count):
            neutral_records.append(coordinate)
        if len(transition_records) == output_count:
            for effect_index, active in enumerate(state):
                effect = transition_records[effect_index]
                if (
                    isinstance(effect, dict)
                    and effect.get("pressed_side") in {"positive", "negative"}
                    and _number(effect.get("press_threshold"))
                    and _number(effect.get("release_threshold"))
                    and not _digital_condition_satisfied(effect, coordinate, bool(active))
                ):
                    errors.append(
                        f"{prefix}.coordinate does not establish output {effect_index} state {active}"
                    )
    if tuple([0] * output_count) not in states or len(neutral_records) != 1 or not (
        _number(neutral) and math.isclose(neutral_records[0], neutral, rel_tol=0.0, abs_tol=1e-12)
    ):
        errors.append("inverse_representatives must contain exactly the neutral all-zero state at neutral_coordinate")
    for effect_index in range(output_count):
        if not any(state[effect_index] == 1 for state in states):
            errors.append(f"inverse_representatives never represent output {effect_index} active")
    return errors


def _input_mapping_errors(value, *, joint_type=None, physical_only=False):
    if not isinstance(value, dict):
        return ["must be an input-mapping object"]
    model = value.get("model")
    if model == "analog_monotone":
        return _analog_mapping_errors(value, physical_only=physical_only)
    if model == "digital_hysteresis":
        return _digital_mapping_errors(value, physical_only=physical_only)
    return ["model must be analog_monotone or digital_hysteresis"]


def _restoring_curve_errors(value, joint_type):
    expected_keys = {
        "model", "equilibrium_coordinate", "coordinate_unit", "positive_coordinate",
        "effort_unit", "effort_quantity", "positive_effort", "branches",
        "branch_selection", "interpolation", "outside_domain", "limitation",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        return [f"must contain exactly {sorted(expected_keys)}"]
    if joint_type not in JOINT_TYPES:
        return ["requires a known joint_type"]
    coordinate_unit = "m" if joint_type == "prismatic" else "rad"
    effort_unit = "N" if joint_type == "prismatic" else "N*m"
    positive_coordinate = (
        "along_joint_axis"
        if joint_type == "prismatic"
        else "right_hand_about_joint_axis"
    )
    errors = []
    if value.get("coordinate_unit") != coordinate_unit:
        errors.append(f"coordinate_unit must be {coordinate_unit!r}")
    if value.get("effort_unit") != effort_unit:
        errors.append(f"effort_unit must be {effort_unit!r}")
    if value.get("positive_coordinate") != positive_coordinate:
        errors.append(f"positive_coordinate must be {positive_coordinate!r}")
    if value.get("effort_quantity") != "internal_generalized_effort_on_child":
        errors.append("effort_quantity must identify internal generalized effort on the child body")
    if value.get("positive_effort") != "along_positive_joint_coordinate":
        errors.append("positive_effort must be along_positive_joint_coordinate")
    equilibrium = value.get("equilibrium_coordinate")
    if not _number(equilibrium):
        errors.append("equilibrium_coordinate must be finite")
        equilibrium = None
    if not isinstance(value.get("limitation"), str) or not value["limitation"].strip():
        errors.append("limitation must explicitly state the curve's applicability")
    if value.get("interpolation") != "piecewise_linear":
        errors.append("interpolation must be piecewise_linear")
    if value.get("outside_domain") != "reject":
        errors.append("outside_domain must be reject; no implicit clamp/extrapolation")

    model = value.get("model")
    branches = value.get("branches")
    if model == "single_valued_no_hysteresis":
        expected_branches = {"single"}
        expected_selection = "single_valued"
    elif model == "loading_release_hysteresis":
        expected_branches = {"loading", "release"}
        expected_selection = (
            "loading_when_abs_displacement_increases_release_when_it_decreases"
        )
    else:
        errors.append(
            "model must be single_valued_no_hysteresis or loading_release_hysteresis"
        )
        expected_branches = set()
        expected_selection = None
    if value.get("branch_selection") != expected_selection:
        errors.append(f"branch_selection must be {expected_selection!r} for model {model!r}")
    if not isinstance(branches, dict) or set(branches) != expected_branches:
        errors.append(f"branches must contain exactly {sorted(expected_branches)}")
        return errors

    domains = []
    for branch_name, curve in branches.items():
        prefix = f"branches.{branch_name}"
        if not isinstance(curve, list) or len(curve) < 2 or not all(
            _vector(point, 2) for point in curve
        ):
            errors.append(f"{prefix} must contain at least two finite [coordinate, effort] points")
            continue
        if not all(curve[index][0] < curve[index + 1][0] for index in range(len(curve) - 1)):
            errors.append(f"{prefix} coordinates must be strictly increasing")
            continue
        domains.append((curve[0][0], curve[-1][0]))
        if equilibrium is not None:
            equilibrium_points = [
                point for point in curve
                if math.isclose(point[0], equilibrium, rel_tol=0.0, abs_tol=1e-12)
            ]
            if len(equilibrium_points) != 1 or not math.isclose(
                equilibrium_points[0][1], 0.0, rel_tol=0.0, abs_tol=1e-12
            ):
                errors.append(f"{prefix} must contain exactly [equilibrium_coordinate, 0]")
            for coordinate, effort in curve:
                product = (coordinate - equilibrium) * effort
                tolerance = 1e-12 * max(1.0, abs(coordinate), abs(effort))
                if product > tolerance:
                    errors.append(
                        f"{prefix} effort must oppose displacement from equilibrium; "
                        "the exporter must not negate it implicitly"
                    )
                    break
    if len(domains) == 2 and domains[0] != domains[1]:
        errors.append("loading and release branches must cover the same coordinate domain")
    if (
        model == "loading_release_hysteresis"
        and len(domains) == 2
        and domains[0] == domains[1]
        and equilibrium is not None
        and all(
            isinstance(branches.get(name), list)
            and len(branches[name]) >= 2
            and all(_vector(point, 2) for point in branches[name])
            and all(
                branches[name][index][0] < branches[name][index + 1][0]
                for index in range(len(branches[name]) - 1)
            )
            for name in ("loading", "release")
        )
    ):
        def interpolate(curve, coordinate):
            for first, second in zip(curve, curve[1:]):
                if first[0] <= coordinate <= second[0]:
                    fraction = (coordinate - first[0]) / (second[0] - first[0])
                    return first[1] + fraction * (second[1] - first[1])
            raise ValueError("coordinate outside curve")

        def integrate(curve, lower, upper):
            knots = [
                lower,
                *[point[0] for point in curve if lower < point[0] < upper],
                upper,
            ]
            return sum(
                0.5
                * (interpolate(curve, first) + interpolate(curve, second))
                * (second - first)
                for first, second in zip(knots, knots[1:])
            )

        lower, upper = domains[0]
        loading, release = branches["loading"], branches["release"]
        amplitudes = sorted({
            point[0]
            for curve in (loading, release)
            for point in curve
            if not math.isclose(point[0], equilibrium, rel_tol=0.0, abs_tol=1e-12)
        })
        cycle_works = []
        for amplitude in amplitudes:
            if amplitude < equilibrium:
                cycle_works.append(
                    integrate(release, amplitude, equilibrium)
                    - integrate(loading, amplitude, equilibrium)
                )
            elif amplitude > equilibrium:
                cycle_works.append(
                    integrate(loading, equilibrium, amplitude)
                    - integrate(release, equilibrium, amplitude)
                )
        scale = max(
            1.0,
            *(abs(point[0] * point[1]) for curve in branches.values() for point in curve),
        )
        tolerance = 1e-12 * scale
        if any(work > tolerance for work in cycle_works):
            errors.append(
                "loading/release hysteresis injects positive net work over a closed "
                "displacement cycle; passive restoring elements require net work <= 0"
            )
    return errors


def _value_errors(key, value, *, joint_type=None, physical_only=False):
    """Validate representations without inventing target-specific bounds."""
    if not _finite_tree(value):
        return ["contains a non-finite or overflowing number"]
    if key == "visual_geometry":
        return _visual_errors(value)
    if key == "metric_scale":
        return [] if (
            _vector(value, 3) and all(component > 0 for component in value)
        ) else ["must be three positive finite metres-per-native-unit values"]
    if key == "root_pose":
        return [] if (
            isinstance(value, dict)
            and set(value) == {"xyz", "rpy"}
            and _vector(value.get("xyz"), 3)
            and _vector(value.get("rpy"), 3)
        ) else ["must contain finite xyz/rpy"]
    if key == "neutral_configuration":
        return [] if (
            isinstance(value, dict)
            and bool(value)
            and all(
                isinstance(joint_id, str)
                and JOINT_ID_RE.fullmatch(joint_id)
                and _number(coordinate)
                for joint_id, coordinate in value.items()
            )
        ) else ["must map stable joint ids to finite coordinates"]
    if key == "constraint_numeric_payload":
        return [] if isinstance(value, dict) and bool(value) and _finite_tree(value) else [
            "must be a non-empty finite numeric payload object"
        ]
    if key == "body_role":
        return [] if value in BODY_ROLES else [f"must be one of {sorted(BODY_ROLES)}"]
    if key == "mass":
        return [] if _positive_number(value) else ["must be finite and positive"]
    if key == "center_of_mass":
        valid = (
            isinstance(value, dict)
            and set(value) == {"xyz", "expressed_in"}
            and value.get("expressed_in") == "body_frame"
            and _vector(value.get("xyz"), 3)
        )
        return [] if valid else ["must be finite xyz expressed_in body_frame"]
    if key == "inertia":
        return _inertia_errors(value)
    if key == "collision_geometry":
        return _collision_errors(value)
    if key == "contact_friction":
        if not isinstance(value, dict) or set(value) != {
            "static_friction", "dynamic_friction", "combine_mode"
        }:
            return [
                "must contain exactly static_friction, dynamic_friction and combine_mode"
            ]
        if not _positive_number(value.get("static_friction"), allow_zero=True) or not _positive_number(
            value.get("dynamic_friction"), allow_zero=True
        ):
            return ["static and dynamic friction must be finite and non-negative"]
        errors = []
        if value["dynamic_friction"] > value["static_friction"]:
            errors.append(
                "dynamic_friction must not exceed static_friction; PhysX would silently raise the latter"
            )
        if value.get("combine_mode") not in PHYSX_COMBINE_MODES:
            errors.append(
                f"combine_mode must be one of {sorted(PHYSX_COMBINE_MODES)}"
            )
        return errors
    if key == "contact_restitution":
        if not isinstance(value, dict) or set(value) != {"coefficient", "combine_mode"}:
            return ["must contain exactly coefficient and combine_mode"]
        errors = []
        if not _positive_number(value.get("coefficient"), upper=1, allow_zero=True):
            errors.append("coefficient must be finite and in [0, 1]")
        if value.get("combine_mode") not in PHYSX_COMBINE_MODES:
            errors.append(
                f"combine_mode must be one of {sorted(PHYSX_COMBINE_MODES)}"
            )
        return errors
    if key == "body_owner":
        return [] if value in {*CONTROLS, "shared"} else ["must name one logical control or 'shared'"]
    if key in {"parent_body", "child_body"}:
        return [] if isinstance(value, str) and JOINT_ID_RE.fullmatch(value) else ["must be a valid body id"]
    if key == "joint_type":
        return [] if isinstance(value, str) and value in JOINT_TYPES else [f"must be one of {sorted(JOINT_TYPES)}"]
    if key == "actuation_mode":
        return [] if value in {"passive", "actuated"} else ["must be passive or actuated"]
    if key == "joint_origin":
        valid = (
            isinstance(value, dict)
            and set(value) == {"xyz", "rpy", "relative_to"}
            and value.get("relative_to") == "parent_body"
            and _vector(value["xyz"], 3)
            and _vector(value["rpy"], 3)
        )
        return [] if valid else ["must be xyz/rpy relative_to parent_body"]
    if key == "joint_axis":
        if not (
            isinstance(value, dict)
            and set(value) == {"xyz", "expressed_in"}
            and value.get("expressed_in") == "joint_frame"
            and _vector(value.get("xyz"), 3)
        ):
            return ["must be finite xyz expressed_in joint_frame"]
        norm = math.sqrt(sum(component * component for component in value["xyz"]))
        return [] if math.isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6) else ["must be a unit vector"]
    if key == "joint_limits":
        if joint_type == "continuous":
            return [] if value == {"unbounded": True} else ["continuous joints must use {'unbounded': true}"]
        if not isinstance(value, dict) or set(value) != {"lower", "upper"}:
            return ["must contain exactly lower and upper; effort/velocity use separately typed fields"]
        if not _number(value.get("lower")) or not _number(value.get("upper")):
            return ["lower and upper must be finite"]
        errors = []
        if value["lower"] >= value["upper"]:
            errors.append("lower limit must be less than upper limit")
        return errors
    if key == "restoring_curve":
        return _restoring_curve_errors(value, joint_type)
    if key in {"damping", "joint_friction"}:
        return [] if _positive_number(value, allow_zero=True) else ["must be finite and non-negative"]
    if key in {"actuator_effort_limit", "actuator_velocity_limit"}:
        return [] if _positive_number(value) else ["must be finite and positive"]
    if key == "input_mapping":
        return _input_mapping_errors(
            value, joint_type=joint_type, physical_only=physical_only
        )
    return ["has no registered value schema"]


_DEFAULT_UNIT = object()


def unknown(name, unit=_DEFAULT_UNIT):
    return {
        "value": None,
        "unit": UNITS.get(name) if unit is _DEFAULT_UNIT else unit,
        "status": "unknown",
        "evidence": [],
        "harness": "audit_spec",
        "reason": f"No verified target-hardware evidence for {name}; no simulator default permitted.",
    }


def intentionally_absent(name, *, evidence, reason, applicability, harness, unit=_DEFAULT_UNIT):
    """Record an evidenced absence; never substitute a simulator dummy value."""
    return {
        "value": None,
        "unit": UNITS.get(name) if unit is _DEFAULT_UNIT else unit,
        "status": "intentionally_absent",
        "evidence": list(evidence),
        "harness": harness,
        "reason": reason,
        "applicability": applicability,
    }


def _channel_schema():
    return {
        "name": "w3c_standard_gamepad_plus_explicit_tensor_order",
        "evidence": ["w3c_gamepad_standard_mapping"],
        "channels": [
            {
                "name": name,
                "kind": kind,
                "tensor_index": tensor_index,
                "standard_index": standard_index,
                "range": list(value_range),
            }
            for name, kind, tensor_index, standard_index, value_range in CHANNEL_DEFINITIONS
        ],
        "note": "The 21-value tensor order is this project's axes-then-buttons transport; W3C defines the four axis and seventeen button indices, not a tensor.",
    }


def _required_effects(name):
    return [
        {"channel": channel, "evidence": ["w3c_gamepad_standard_mapping"]}
        for channel in CONTROL_EFFECTS[name]
    ]


def _physical_only_schema():
    return {
        "pair": {
            "aliases": ["Pair", "Bind", "Connect", "Sync"],
            "evidence": ["apple_1708_connect_button", "ifixit_1708_buttons"],
            "standard_gamepad_channel": None,
            "reason": "The 1708 has this physical control, but it is absent from the W3C Standard Gamepad's 17 buttons and 4 axes.",
        }
    }


def _unknown_motion_model(name):
    is_pair = name == "pair"
    return {
        "status": "unknown",
        "joints": [],
        "required_control_effects": _required_effects(name),
        "physical_only": is_pair,
        "identity_evidence": ["apple_1708_connect_button", "ifixit_1708_buttons"] if is_pair else [],
        "configuration_domain": {
            "status": "unknown",
            "constraint_ids": [],
            "combination": None,
            "independent_joint_ids": [],
            "neutral_configuration": None,
            "neutral_configuration_evidence": unknown(
                "neutral_configuration", unit="per_joint_coordinate_units"
            ),
            "approximation": None,
            "evidence": [],
            "harness": "audit_spec",
            "reason": f"No verified coupled configuration domain for {name}.",
            "applicability": None,
        },
        "evidence": [],
        "harness": "audit_spec",
        "reason": f"No verified Xbox 1708 mechanism topology for {name}; no joints inferred from visual meshes.",
        "applicability": None,
    }


def _unknown_physical_topology():
    return {
        "status": "unknown",
        "bodies": [],
        "configuration_constraints": [],
        "root_attachment": {
            "status": "unknown",
            "mode": None,
            "root_body": None,
            "reference_frame": None,
            "pose": None,
            "pose_unit": "m,rad",
            "pose_evidence": unknown("root_pose", unit="m,rad"),
            "evidence": [],
            "harness": "audit_spec",
            "reason": "Controller instance attachment (free, fixed, kinematic or fixture-mounted) is unresolved.",
            "applicability": None,
        },
        "self_collision_policy": {
            "status": "unknown",
            "default": None,
            "pair_overrides": [],
            "evidence": [],
            "harness": "audit_spec",
            "reason": "Articulation self-collision pairs are unresolved; no PhysX default is permitted.",
            "applicability": None,
        },
        "evidence": [],
        "harness": "audit_spec",
        "reason": "No verified Xbox 1708 rigid-body graph; no body or joint is inferred from visual meshes.",
        "applicability": None,
    }


def _catalog_sha256(catalog):
    return hashlib.sha256(
        json.dumps(catalog, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _document_sha256(document):
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _load_asset_registry(asset_registry=None):
    if asset_registry is not None:
        return asset_registry
    return json.loads(ASSET_REGISTRY_PATH.read_text())


def _asset_registry_binding(asset_registry):
    return {
        "path": ASSET_REGISTRY_SPEC_PATH,
        "path_base": "repository_root",
        "sha256": _document_sha256(asset_registry),
        "registry_role": "canonical_status_authority",
        "visual_candidate_collections": list(ASSET_ID_COLLECTIONS),
    }


def _audit_viewer_adapter_gate(asset_registry, errors):
    """Bind the schema-1 preview blocker to its reviewed acceptance document."""
    gate = (
        asset_registry.get("physical_asset", {}).get("viewer_adapter")
        if isinstance(asset_registry, dict)
        and isinstance(asset_registry.get("physical_asset"), dict)
        else None
    )
    prefix = "asset registry: physical_asset.viewer_adapter"
    expected_keys = {
        "status", "canonical_schema_version", "viewer_schema_version",
        "implementation", "physical_acceptance_allowed",
        "interactive_acceptance", "interactive_acceptance_sha256",
    }
    if not isinstance(gate, dict) or set(gate) != expected_keys:
        errors.append(f"{prefix}: fields changed")
        return
    if (
        gate.get("status") != "blocked_unimplemented"
        or gate.get("canonical_schema_version") != SCHEMA_VERSION
        or gate.get("viewer_schema_version") != 1
        or gate.get("implementation") is not None
        or gate.get("physical_acceptance_allowed") is not False
    ):
        errors.append(f"{prefix}: preview must remain fail-closed until an adapter is implemented")
    relative = gate.get("interactive_acceptance")
    expected_hash = gate.get("interactive_acceptance_sha256")
    path = _registry_manifest_path(relative)
    if path is None:
        errors.append(f"{prefix}.interactive_acceptance: must be repository-root-relative")
        return
    if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
        errors.append(f"{prefix}.interactive_acceptance_sha256: invalid")
        return
    try:
        raw = path.read_bytes()
        acceptance = json.loads(raw)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        errors.append(f"{prefix}.interactive_acceptance: unreadable JSON")
        return
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        errors.append(f"{prefix}: interactive acceptance SHA256 mismatch")
    acceptance_gate = acceptance.get("canonical_adapter") if isinstance(acceptance, dict) else None
    if not isinstance(acceptance_gate, dict) or (
        acceptance_gate.get("status") != "blocked_unimplemented"
        or acceptance_gate.get("canonical_schema_version") != SCHEMA_VERSION
        or acceptance_gate.get("viewer_schema_version") != 1
        or acceptance_gate.get("implementation") is not None
        or acceptance_gate.get("physical_acceptance_allowed") is not False
    ):
        errors.append(f"{prefix}: acceptance document does not carry the same fail-closed blocker")
    gates = acceptance.get("acceptance_gates") if isinstance(acceptance, dict) else None
    adapter_gates = [
        item for item in gates if isinstance(item, dict)
        and item.get("id") == "canonical_v2_to_viewer_adapter"
    ] if isinstance(gates, list) else []
    if len(adapter_gates) != 1 or adapter_gates[0].get("passed") is not False:
        errors.append(f"{prefix}: canonical adapter acceptance gate must exist exactly once and fail")


def _registry_manifest_path(value):
    if not _safe_relative_asset_path(value):
        return None
    path = (ROOT / value).resolve()
    return path if path == ROOT or ROOT in path.parents else None


def _registered_visual_bindings(asset_registry, catalog_sources, errors):
    if not isinstance(asset_registry, dict):
        errors.append("asset registry: root must be an object")
        return set(), {}
    if asset_registry.get("registry_role") != "canonical_status_authority":
        errors.append("asset registry: registry_role must be canonical_status_authority")
    expected_path_bases = {
        "metadata_links": "asset_index_directory",
        "visual_manifest_path": "repository_root",
        "viewer_adapter_acceptance": "repository_root",
        "external_gpu_paths": "absolute_external",
    }
    if asset_registry.get("path_bases") != expected_path_bases:
        errors.append("asset registry: path_bases must declare the canonical per-field bases")
    target_revision = (
        asset_registry.get("target_hardware", {}).get("revision")
        if isinstance(asset_registry.get("target_hardware"), dict)
        else None
    )
    approved_target_id = asset_registry.get("approved_target_geometry_candidate_id")
    if approved_target_id is not None and (
        not isinstance(approved_target_id, str)
        or not JOINT_ID_RE.fullmatch(approved_target_id)
    ):
        errors.append("asset registry: approved_target_geometry_candidate_id is invalid")
    registered = set()
    approved_ids = set()
    bindings = {}
    for collection_name in ASSET_ID_COLLECTIONS:
        collection = asset_registry.get(collection_name)
        if not isinstance(collection, dict):
            errors.append(f"asset registry: {collection_name} must be an object")
            continue
        for candidate_id, record in collection.items():
            if not isinstance(candidate_id, str) or not JOINT_ID_RE.fullmatch(candidate_id):
                errors.append(
                    f"asset registry: {collection_name} contains an invalid candidate id"
                )
                continue
            if not isinstance(record, dict):
                errors.append(
                    f"asset registry: {collection_name}.{candidate_id} must be an object"
                )
                continue
            if candidate_id in registered:
                errors.append(
                    f"asset registry: duplicate visual candidate id {candidate_id!r}"
                )
            registered.add(candidate_id)
            approval = record.get("target_visual_geometry_approval")
            approval_prefix = (
                f"asset registry: {collection_name}.{candidate_id}."
                "target_visual_geometry_approval"
            )
            approval_keys = {
                "approved", "target_revision", "shape_identity_verified", "evidence",
                "reason",
            }
            approved_for_target = False
            if not isinstance(approval, dict) or set(approval) != approval_keys:
                errors.append(f"{approval_prefix}: fields changed")
            else:
                approved = approval.get("approved")
                reason = approval.get("reason")
                if type(approved) is not bool:
                    errors.append(f"{approval_prefix}.approved must be boolean")
                if not isinstance(reason, str) or not reason.strip():
                    errors.append(f"{approval_prefix}.reason is required")
                evidence = approval.get("evidence")
                if approved is True:
                    if candidate_id != approved_target_id:
                        errors.append(
                            f"{approval_prefix}: approved record must be selected by "
                            "approved_target_geometry_candidate_id"
                        )
                    if approval.get("target_revision") != target_revision:
                        errors.append(f"{approval_prefix}: target revision does not match registry target")
                    if approval.get("shape_identity_verified") is not True:
                        errors.append(f"{approval_prefix}: shape identity is not verified")
                    if record.get("shape_revision_match") is False:
                        errors.append(f"{approval_prefix}: contradicts shape_revision_match=false")
                    if record.get("controller_revision_verified") is False:
                        errors.append(f"{approval_prefix}: contradicts controller_revision_verified=false")
                    if record.get("purpose") == "viewer software regression only":
                        errors.append(f"{approval_prefix}: viewer-only record cannot be target geometry")
                    if not isinstance(evidence, list) or not evidence:
                        errors.append(f"{approval_prefix}.evidence must bind at least one reviewed artifact")
                    else:
                        for evidence_index, item in enumerate(evidence):
                            evidence_path = f"{approval_prefix}.evidence[{evidence_index}]"
                            if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                                errors.append(f"{evidence_path}: must bind path and SHA256")
                                continue
                            path = _registry_manifest_path(item.get("path"))
                            digest = item.get("sha256")
                            if path is None or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                                errors.append(f"{evidence_path}: invalid path/SHA256")
                                continue
                            try:
                                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                            except OSError:
                                actual = None
                            if actual != digest:
                                errors.append(f"{evidence_path}: reviewed artifact SHA256 mismatch")
                    approved_for_target = (
                        candidate_id == approved_target_id
                        and approval.get("target_revision") == target_revision
                        and approval.get("shape_identity_verified") is True
                        and isinstance(evidence, list)
                        and bool(evidence)
                    )
                    if approved_for_target:
                        approved_ids.add(candidate_id)
                else:
                    if (
                        approval.get("target_revision") is not None
                        or approval.get("shape_identity_verified") is not False
                        or evidence != []
                    ):
                        errors.append(
                            f"{approval_prefix}: unapproved record cannot claim target revision, "
                            "verified shape identity or approval evidence"
                        )
            manifest_binding = record.get("visual_manifest")
            if manifest_binding is None:
                continue
            prefix = f"asset registry: {collection_name}.{candidate_id}.visual_manifest"
            if not isinstance(manifest_binding, dict) or set(manifest_binding) != {
                "path", "sha256", "artifacts"
            }:
                errors.append(f"{prefix} must contain exactly path, sha256 and artifacts")
                continue
            manifest_path = _registry_manifest_path(manifest_binding.get("path"))
            expected_manifest_hash = manifest_binding.get("sha256")
            if manifest_path is None:
                errors.append(f"{prefix}.path must be safe and repository-root-relative")
                continue
            if not isinstance(expected_manifest_hash, str) or not SHA256_RE.fullmatch(
                expected_manifest_hash
            ):
                errors.append(f"{prefix}.sha256 must be a lowercase SHA256")
                continue
            try:
                raw = manifest_path.read_bytes()
            except OSError:
                errors.append(f"{prefix}.path is not a readable tracked manifest")
                continue
            if hashlib.sha256(raw).hexdigest() != expected_manifest_hash:
                errors.append(f"{prefix}: tracked manifest SHA256 mismatch")
                continue
            try:
                manifest = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                errors.append(f"{prefix}: tracked manifest is not valid JSON")
                continue
            artifacts = manifest_binding.get("artifacts")
            if not isinstance(artifacts, dict):
                errors.append(f"{prefix}.artifacts must be an object")
                continue
            for artifact_id, artifact in artifacts.items():
                artifact_prefix = f"{prefix}.artifacts.{artifact_id}"
                if not isinstance(artifact_id, str) or not JOINT_ID_RE.fullmatch(artifact_id):
                    errors.append(f"{artifact_prefix}: invalid artifact id")
                    continue
                if not isinstance(artifact, dict):
                    errors.append(f"{artifact_prefix}: artifact binding must be an object")
                    continue
                mode = artifact.get("mode")
                common = {
                    "mode", "manifest_entry", "metric_scale"
                }
                expected_keys = (
                    common | {"file", "sha256"}
                    if mode == "container_objects"
                    else common
                )
                if mode not in {"container_objects", "object_files"} or set(artifact) != expected_keys:
                    errors.append(
                        f"{artifact_prefix}: unsupported mode or fields; expected a closed container_objects/object_files binding"
                    )
                    continue
                scale_field = artifact.get("metric_scale")
                registry_missing = []
                scale_errors_start = len(errors)
                _audit_field(
                    f"{artifact_prefix}.metric_scale", scale_field, "metric_scale",
                    "m/native_unit", catalog_sources, errors, registry_missing,
                )
                scale = (
                    scale_field.get("value") if isinstance(scale_field, dict) else None
                )
                scale_known_valid = scale is not None and len(errors) == scale_errors_start
                if approved_for_target and not scale_known_valid:
                    errors.append(
                        f"{artifact_prefix}.metric_scale: target visual approval requires "
                        "a known evidence-bound scale with uncertainty"
                    )
                manifest_entry = artifact.get("manifest_entry")
                if not isinstance(manifest_entry, str) or manifest_entry not in manifest:
                    errors.append(f"{artifact_prefix}.manifest_entry does not resolve")
                    continue
                entry = manifest[manifest_entry]
                if mode == "container_objects":
                    file = artifact.get("file")
                    sha256 = artifact.get("sha256")
                    if not _safe_relative_asset_path(file) or not isinstance(
                        sha256, str
                    ) or not SHA256_RE.fullmatch(sha256):
                        errors.append(f"{artifact_prefix}: invalid file/SHA256")
                        continue
                    if not isinstance(entry, dict) or not isinstance(entry.get("objects"), list):
                        errors.append(f"{artifact_prefix}: manifest entry has no object list")
                        continue
                    manifest_file = entry.get("file")
                    normalized_manifest_file = (
                        manifest_file.replace("\\", "/")
                        if isinstance(manifest_file, str)
                        else ""
                    )
                    if not (
                        normalized_manifest_file == file
                        or normalized_manifest_file.endswith("/" + file)
                    ):
                        errors.append(f"{artifact_prefix}: artifact file disagrees with manifest")
                    if entry.get("sha256") != sha256:
                        errors.append(
                            f"{artifact_prefix}: artifact SHA256 is not bound by the tracked manifest entry"
                        )
                        continue
                    object_records = entry["objects"]
                    fixed_file, fixed_sha256 = file, sha256
                else:
                    if not isinstance(entry, list):
                        errors.append(f"{artifact_prefix}: manifest entry must be an object-file list")
                        continue
                    object_records = entry
                    fixed_file = fixed_sha256 = None
                for object_index, object_record in enumerate(object_records):
                    if not isinstance(object_record, dict):
                        errors.append(f"{artifact_prefix}: object[{object_index}] is invalid")
                        continue
                    object_id = object_record.get("name")
                    if not isinstance(object_id, str) or not object_id.strip():
                        errors.append(f"{artifact_prefix}: object[{object_index}] has no stable name")
                        continue
                    if mode == "container_objects":
                        if object_record.get("type") != "MESH":
                            continue
                        file, sha256 = fixed_file, fixed_sha256
                    else:
                        file, sha256 = object_record.get("file"), object_record.get("sha256")
                        if not _safe_relative_asset_path(file) or not isinstance(
                            sha256, str
                        ) or not SHA256_RE.fullmatch(sha256):
                            errors.append(
                                f"{artifact_prefix}: object[{object_index}] lacks a safe file/SHA256 binding"
                            )
                            continue
                    key = (candidate_id, artifact_id, object_id)
                    if key in bindings:
                        errors.append(f"{artifact_prefix}: duplicate object binding {object_id!r}")
                        continue
                    if approved_for_target and scale_known_valid:
                        bindings[key] = {
                            "file": file,
                            "sha256": sha256,
                            "meters_per_native_unit": scale,
                            "manifest_path": manifest_binding["path"],
                            "manifest_sha256": expected_manifest_hash,
                        }
    if approved_target_id is not None and approved_target_id not in approved_ids:
        errors.append(
            "asset registry: approved_target_geometry_candidate_id does not resolve to exactly "
            "one target-visual-geometry-approved record"
        )
    return registered, bindings


def make_spec(catalog, asset_registry=None):
    asset_registry = _load_asset_registry(asset_registry)
    parts = {
        name: {"motion_model": _unknown_motion_model(name)}
        for name in CONTROLS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_sha256": _catalog_sha256(catalog),
        "asset_registry_binding": _asset_registry_binding(asset_registry),
        "hardware_revision": {
            "value": "1708",
            "unit": None,
            "status": "user_confirmed",
            "evidence": ["user_target_1708"],
            "harness": "audit_spec",
            "applicability": "Owner identifies the Xbox One 1708 as the target; no physical measurements inferred.",
        },
        "status": "incomplete_not_for_dynamics_or_RL",
        "component_inventory_basis": {
            "evidence": ["user_target_1708", "ifixit_1708_buttons", "apple_1708_connect_button"],
            "scope": "1708 target; visual source remains unverified for this revision. Includes the physical Pair/Bind/Connect control and no Share control.",
            "harness": "audit_spec",
        },
        "input_schema": _channel_schema(),
        "physical_only_controls": _physical_only_schema(),
        "physical_topology": _unknown_physical_topology(),
        "parts": parts,
        "reference_candidates": {
            "left_stick": [
                "stick_direction_limit",
                "stick_operating_torque",
                "stick_click_force",
                "stick_click_travel",
                "stick_return_precision",
            ],
            "right_stick": [
                "stick_direction_limit",
                "stick_operating_torque",
                "stick_click_force",
                "stick_click_travel",
                "stick_return_precision",
            ],
            **{name: ["front_force", "front_travel"] for name in ("a", "b", "x", "y")},
            **{
                name: ["shoulder_force", "shoulder_travel"]
                for name in ("left_shoulder", "right_shoulder")
            },
        },
        "reference_policy": "Candidates are NOT assigned to target parameters. Adoption requires explicit applicability rationale, unit-correct derivation and a test.",
        "evidence_field_policy": "Known target fields use measured, derived, estimated or reference status. Measured values bind an instrument and workspace measurement protocol; derived/estimated values bind explicit inputs, method, uncertainty range and confidence meaning; reference values bind an adoption rule and applicability. Every known-value harness is a safe existing workspace path, and Python entrypoints are statically resolved. Synthetic fixtures are not a canonical target-value status.",
        "frame_convention": {
            "handedness": "right_handed",
            "translation_axes": "parent_frame_cartesian_xyz",
            "rotation_representation": "urdf_fixed_axis_extrinsic_xyz_rpy",
            "rotation_unit": "rad",
            "joint_axis_frame": "joint_frame_after_origin_transform",
        },
        "topology_policy": "Visual bindings, mass, inertia and colliders belong to globally unique bodies in physical_topology.bodies; no logical control is treated as one implicit rigid body. body_owner is a provenance/organization label only: it does not restrict joint endpoints, because one physical body may participate in shared or cross-control mechanisms. Joints are uniquely owned under one logical control but reference global parent/child body ids, and all joints together form one controller graph. A virtual_frame is a representation-only coordinate frame and must carry evidenced intentionally-absent geometry, mass, inertia and contact data; exporters must lower it to a supported compound joint or reject it, never synthesize a tiny-mass link. Visual candidate/artifact/object IDs and file hashes must resolve through a SHA-bound canonical registry manifest and an explicit target-visual-geometry approval. Visual/collision files are safe paths relative to an explicit artifact root supplied at verification/export time. A valid schema is not a validated URDF or SAPIEN asset.",
        "mesh_unit_policy": "Every visual or collision mesh declares three positive meters_per_native_unit values with unit m/native_unit. A value of [1,1,1] is valid only when evidence establishes that each native mesh unit is one metre; OBJ or other unitless formats must not be assigned an implicit scale.",
        "curve_policy": "Restoring curves declare equilibrium, internal-effort sign, hysteresis branches, interpolation and reject-outside behavior. Analog mappings are monotone, full-range and uniquely invertible. Digital controls instead declare press/release thresholds, Schmitt-trigger state, and evidenced representative coordinates without claiming a unique inverse. Pair uses the same digital physics with output_kind physical_event and never creates a tensor channel. Any differentiable training surrogate is a separately named approximation artifact, never physical ground truth. Finite joint limits must be the exact mapping/curve domain.",
        "configuration_constraint_policy": "Coupled multi-joint controls declare intersection constraints plus explicit independent_joint_ids, or an explicit approximation/unmodeled domain. Constraint and independent sets cover every owned joint exactly. A full neutral_configuration is checked against joint equilibria, limits and every constraint as a feasibility witness. Exporters must not assume omitted Cartesian factors.",
        "simulator_policy": {
            "evidence": [
                "physx_shape_offsets", "sapien_collision_groups",
                "physx_rigid_body_collision",
            ],
            "harness": "audit_spec",
            "scope": "Every collider declares SAPIEN's four uint32 filter words and finite PhysX contact/rest offsets with restOffset strictly below non-negative contactOffset. Triangle meshes declare simulation/query role, exact actor kind, mobility and cooking; a non-kinematic dynamic simulation mesh requires SHA-bound SDF cooking and GPU dynamics. In a reduced-coordinate articulation every body, including an eFIX_BASE root, is a non-kinematic articulation link; only a standalone fixed body is a rigid static actor. Direct parent-child link collision is backend-unconditionally disabled and a policy may not claim it is enabled. A modeled topology declares root attachment and articulation self-collision policy, and mesh actor declarations must agree with graph role. Joint limits are physical coordinate stops. Passive joints mark actuator limits intentionally absent; simulator safety clamps are separate explicit configuration. Exact PhysX version/cooking parameters or a SHA-bound pre-cooked no-recook artifact remain required before dynamics readiness. No PhysX/SAPIEN default is evidence.",
        },
        "contact_material_policy": {
            "evidence": ["physx_material"],
            "harness": "audit_spec",
            "scope": "Contact friction records separate static and dynamic coefficients plus an explicit PhysX combine mode. Restitution records its coefficient and combine mode. No PhysX material default is implied, and compliant negative restitution is outside this schema.",
        },
        "dpad_policy": "Required logical directions do not imply four independent buttons. A future motion_model may use one or more joints, and one joint may map to multiple coupled effects.",
        "stick_policy": "Each stick requires X, Y and click effects, but their joint count, axes, coupling and limits remain unresolved. Never infer pivots from Blender origins.",
        "trigger_policy": "Do not replace analog triggers with Alpakka digital trigger switches.",
        "interactive_adapter_gate": {
            "status": "blocked_unimplemented",
            "canonical_schema_version": SCHEMA_VERSION,
            "viewer_schema_version": 1,
            "adapter": None,
            "reason": "No fail-closed, hash-bound v2-to-viewer adapter currently proves that the schema-1 preview preserves body/joint graphs, coupled constraints, virtual frames and inverse mappings. Viewer roundtrips are software previews, not physical-asset acceptance.",
        },
        "excluded_visual_controls": {
            "share": {
                "reason": "Not part of confirmed 1708 target; original meshes retained unchanged"
            }
        },
    }


def synchronize_spec(current, catalog, asset_registry=None):
    """Refresh immutable metadata without replacing any editable physical data."""
    if not isinstance(current, dict) or current.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"sync-spec only supports schema version {SCHEMA_VERSION}; explicit migration required"
        )
    synchronized = make_spec(catalog, asset_registry=asset_registry)

    def add_missing_keys(target, template):
        if not isinstance(target, dict) or not isinstance(template, dict):
            return
        for key, template_value in template.items():
            if key not in target:
                target[key] = copy.deepcopy(template_value)
            elif isinstance(target[key], dict) and isinstance(template_value, dict):
                add_missing_keys(target[key], template_value)

    for editable in ("physical_topology", "parts"):
        if editable in current:
            synchronized[editable] = copy.deepcopy(current[editable])
            add_missing_keys(synchronized[editable], make_spec(
                catalog, asset_registry=asset_registry
            )[editable])
    return synchronized


def validated_synchronize_spec(current, catalog, asset_registry=None):
    """Preserve editable data, then reject a synchronized candidate that fails audit."""
    synchronized = synchronize_spec(current, catalog, asset_registry=asset_registry)
    report = audit(
        synchronized, catalog, asset_registry=asset_registry
    )
    return synchronized, report


def _valid_refs(refs, catalog_sources, *, allow_empty=False):
    return (
        isinstance(refs, list)
        and (allow_empty or bool(refs))
        and all(isinstance(ref, str) and ref in catalog_sources for ref in refs)
    )


def _known_harness_errors(value):
    expected = {"kind", "path", "entrypoint"}
    if not isinstance(value, dict) or set(value) != expected:
        return ["known-value harness must contain exactly kind, path and entrypoint"]
    errors = []
    kind = value.get("kind")
    if kind not in {
        "python_derivation", "python_test", "measurement_protocol", "reference_review"
    }:
        errors.append("harness.kind is unsupported")
    path = value.get("path")
    if not _safe_relative_asset_path(path):
        errors.append("harness.path must be a safe repository-relative path")
    elif not (ROOT / path).is_file():
        errors.append("harness.path must resolve to a tracked or workspace file")
    entrypoint = value.get("entrypoint")
    if kind in {"python_derivation", "python_test"}:
        if not isinstance(path, str) or not path.endswith(".py"):
            errors.append("Python harnesses must point to a .py file")
        if not isinstance(entrypoint, str) or not entrypoint.strip():
            errors.append("Python harnesses require a named entrypoint")
        elif _safe_relative_asset_path(path) and (ROOT / path).is_file():
            try:
                tree = ast.parse((ROOT / path).read_text())
            except (OSError, SyntaxError, UnicodeError):
                errors.append("Python harness cannot be parsed")
            else:
                scope = tree.body
                found = True
                for segment in entrypoint.split("."):
                    matches = [
                        node for node in scope
                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == segment
                    ]
                    if len(matches) != 1:
                        found = False
                        break
                    scope = matches[0].body if isinstance(matches[0], ast.ClassDef) else []
                if not found:
                    errors.append("Python harness entrypoint does not exist in the declared file")
    elif entrypoint is not None and (
        not isinstance(entrypoint, str) or not entrypoint.strip()
    ):
        errors.append("non-Python harness entrypoint must be null or a non-empty locator")
    return errors


def _append_harness_errors(path, value, errors):
    errors.extend(
        f"{path}: {detail}" for detail in _known_harness_errors(value)
    )


def _uncertainty_errors(value, field_value, expected_unit):
    expected = {"type", "range", "unit", "quantity", "confidence"}
    if not isinstance(value, dict) or set(value) != expected:
        return ["uncertainty must contain exactly type, range, unit, quantity and confidence"]
    errors = []
    uncertainty_type = value.get("type")
    bounds = value.get("range")
    if uncertainty_type not in {"bounded_interval", "bounded_error"}:
        errors.append("uncertainty.type must be bounded_interval or bounded_error")
    if not _vector(bounds, 2) or bounds[0] > bounds[1]:
        errors.append("uncertainty.range must be finite [lower, upper] with lower <= upper")
    elif uncertainty_type == "bounded_interval":
        if not _number(field_value):
            errors.append("bounded_interval is only valid for a scalar numeric field value")
        elif not bounds[0] <= field_value <= bounds[1]:
            errors.append("bounded_interval must contain the field value")
    elif uncertainty_type == "bounded_error" and bounds[0] < 0:
        errors.append("bounded_error range cannot contain negative error magnitudes")
    if value.get("unit") != expected_unit:
        errors.append("uncertainty.unit must equal the field unit")
    if not isinstance(value.get("quantity"), str) or not value["quantity"].strip():
        errors.append("uncertainty.quantity must define what the range bounds")
    confidence = value.get("confidence")
    if not isinstance(confidence, dict) or set(confidence) != {"kind", "level", "meaning"}:
        errors.append("uncertainty.confidence must contain kind, level and meaning")
    else:
        kind = confidence.get("kind")
        level = confidence.get("level")
        if kind == "coverage_probability":
            if not _number(level) or not 0 < level <= 1:
                errors.append("coverage_probability confidence requires level in (0, 1]")
        elif kind in {"engineering_bound", "non_statistical"}:
            if level is not None:
                errors.append(f"{kind} confidence must use null level")
        else:
            errors.append("uncertainty.confidence.kind is unsupported")
        if not isinstance(confidence.get("meaning"), str) or not confidence["meaning"].strip():
            errors.append("uncertainty.confidence.meaning is required")
    return errors


def _derivation_errors(value, catalog_sources):
    if not isinstance(value, dict) or set(value) != {"method", "inputs", "evidence"}:
        return ["derivation must contain exactly method, inputs and evidence"]
    errors = []
    if not isinstance(value.get("method"), str) or not value["method"].strip():
        errors.append("derivation.method is required")
    if not _valid_refs(value.get("evidence"), catalog_sources):
        errors.append("derivation.evidence is missing or invalid")
    inputs = value.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        errors.append("derivation.inputs must be a non-empty list")
        return errors
    for index, item in enumerate(inputs):
        if not isinstance(item, dict) or set(item) != {"name", "value", "unit", "evidence"}:
            errors.append(f"derivation.inputs[{index}] fields changed")
            continue
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            errors.append(f"derivation.inputs[{index}].name is required")
        if item.get("value") is None or not _finite_tree(item.get("value")):
            errors.append(f"derivation.inputs[{index}].value must be explicit and finite")
        if item.get("unit") is not None and (
            not isinstance(item.get("unit"), str) or not item["unit"].strip()
        ):
            errors.append(f"derivation.inputs[{index}].unit is invalid")
        if not _valid_refs(item.get("evidence"), catalog_sources):
            errors.append(f"derivation.inputs[{index}].evidence is missing or invalid")
    return errors


def _measurement_errors(value):
    expected = {"protocol_path", "instrument", "sample_count", "method"}
    if not isinstance(value, dict) or set(value) != expected:
        return ["measurement must contain protocol_path, instrument, sample_count and method"]
    errors = []
    protocol = value.get("protocol_path")
    if not _safe_relative_asset_path(protocol) or not (ROOT / protocol).is_file():
        errors.append("measurement.protocol_path must resolve to a safe workspace protocol")
    instrument = value.get("instrument")
    if not isinstance(instrument, dict) or set(instrument) != {
        "manufacturer", "model", "identifier", "resolution", "resolution_unit"
    }:
        errors.append("measurement.instrument fields changed")
    else:
        for key in ("manufacturer", "model", "identifier"):
            if not isinstance(instrument.get(key), str) or not instrument[key].strip():
                errors.append(f"measurement.instrument.{key} is required")
        if not _positive_number(instrument.get("resolution")):
            errors.append("measurement.instrument.resolution must be positive and finite")
        if not isinstance(instrument.get("resolution_unit"), str) or not instrument["resolution_unit"].strip():
            errors.append("measurement.instrument.resolution_unit is required")
    if type(value.get("sample_count")) is not int or value["sample_count"] <= 0:
        errors.append("measurement.sample_count must be a positive integer")
    if not isinstance(value.get("method"), str) or not value["method"].strip():
        errors.append("measurement.method is required")
    return errors


def _reference_adoption_errors(value, evidence, catalog_sources):
    if not isinstance(value, dict) or set(value) != {"source_id", "adoption_rule"}:
        return ["reference must contain exactly source_id and adoption_rule"]
    errors = []
    source_id = value.get("source_id")
    if source_id not in catalog_sources or source_id not in (evidence or []):
        errors.append("reference.source_id must resolve and appear in field evidence")
    if not isinstance(value.get("adoption_rule"), str) or not value["adoption_rule"].strip():
        errors.append("reference.adoption_rule is required")
    return errors


def _audit_field(path, item, key, expected_unit, catalog_sources, errors, missing,
                 *, joint_type=None, physical_only=False, allow_absent=False):
    if not isinstance(item, dict):
        errors.append(f"{path}: field missing")
        return
    if item.get("unit") != expected_unit:
        errors.append(f"{path}: wrong units; expected {expected_unit!r}")
    if item.get("value") is None:
        if item.get("status") == "intentionally_absent" and allow_absent:
            if set(item) != {
                "value", "unit", "status", "evidence", "harness", "reason",
                "applicability",
            }:
                errors.append(f"{path}: intentionally absent field keys changed")
            if (
                not _valid_refs(item.get("evidence"), catalog_sources)
                or not isinstance(item.get("reason"), str)
                or not item.get("reason").strip()
                or not isinstance(item.get("harness"), str)
                or not item.get("harness").strip()
                or not isinstance(item.get("applicability"), str)
                or not item.get("applicability").strip()
            ):
                errors.append(f"{path}: intentionally absent requires evidence, harness and rationale")
        else:
            missing.append(path)
            if set(item) != {"value", "unit", "status", "evidence", "harness", "reason"}:
                errors.append(f"{path}: unknown field keys changed")
            if (
                item.get("status") != "unknown"
                or not isinstance(item.get("reason"), str)
                or not item.get("reason").strip()
                or item.get("evidence") != []
                or not isinstance(item.get("harness"), str)
                or not item.get("harness").strip()
            ):
                errors.append(f"{path}: undocumented unknown")
        return
    common_keys = {"value", "unit", "status", "evidence", "harness", "applicability"}
    status = item.get("status")
    status_keys = {
        "derived": common_keys | {"derivation", "uncertainty"},
        "estimated": common_keys | {"derivation", "uncertainty"},
        "measured": common_keys | {"measurement", "uncertainty"},
        "reference": common_keys | {"reference"},
    }
    expected_keys = status_keys.get(status)
    if expected_keys is None:
        errors.append(f"{path}: unsupported evidence status")
    elif set(item) != expected_keys:
        errors.append(f"{path}: known field keys changed for status {status!r}")
    if not _valid_refs(item.get("evidence"), catalog_sources):
        errors.append(f"{path}: missing/invalid evidence")
    if (
        not isinstance(item.get("applicability"), str)
        or not item.get("applicability").strip()
    ):
        errors.append(f"{path}: missing applicability")
    errors.extend(
        f"{path}: {detail}" for detail in _known_harness_errors(item.get("harness"))
    )
    if status in {"derived", "estimated"}:
        errors.extend(
            f"{path}: {detail}"
            for detail in _derivation_errors(item.get("derivation"), catalog_sources)
        )
        if key == "metric_scale":
            derivation = item.get("derivation")
            inputs = derivation.get("inputs") if isinstance(derivation, dict) else None
            anchors = [
                record for record in inputs if isinstance(record, dict)
                and record.get("name") == "derived_meters_per_native_unit"
            ] if isinstance(inputs, list) else []
            if len(anchors) != 1 or anchors[0].get("value") != item.get("value"):
                errors.append(
                    f"{path}: metric-scale derivation must bind exactly one "
                    "derived_meters_per_native_unit input equal to the declared scale"
                )
        errors.extend(
            f"{path}: {detail}"
            for detail in _uncertainty_errors(
                item.get("uncertainty"), item.get("value"), expected_unit
            )
        )
        harness = item.get("harness")
        if not isinstance(harness, dict) or harness.get("kind") != "python_derivation":
            errors.append(f"{path}: {status} requires a python_derivation harness")
    elif status == "measured":
        errors.extend(
            f"{path}: {detail}" for detail in _measurement_errors(item.get("measurement"))
        )
        errors.extend(
            f"{path}: {detail}"
            for detail in _uncertainty_errors(
                item.get("uncertainty"), item.get("value"), expected_unit
            )
        )
        harness = item.get("harness")
        if not isinstance(harness, dict) or harness.get("kind") != "measurement_protocol":
            errors.append(f"{path}: measured requires a measurement_protocol harness")
    elif status == "reference":
        errors.extend(
            f"{path}: {detail}"
            for detail in _reference_adoption_errors(
                item.get("reference"), item.get("evidence"), catalog_sources
            )
        )
        harness = item.get("harness")
        if not isinstance(harness, dict) or harness.get("kind") != "reference_review":
            errors.append(f"{path}: reference requires a reference_review harness")
    for detail in _value_errors(
        key,
        item.get("value"),
        joint_type=joint_type,
        physical_only=physical_only,
    ):
        errors.append(f"{path}: {detail}")


def _audit_body(
    body, index, catalog_sources, registered_candidate_ids,
    registered_visual_bindings, errors, missing,
):
    path = f"physical_topology.bodies[{index}]"
    expected_keys = {"id", "body_owner", *BODY_FIELDS}
    if not isinstance(body, dict):
        errors.append(f"{path}: body must be an object")
        return None
    if set(body) != expected_keys:
        errors.append(f"{path}: body fields changed")
    body_id = body.get("id")
    if not isinstance(body_id, str) or not JOINT_ID_RE.fullmatch(body_id):
        errors.append(f"{path}.id: must match {JOINT_ID_RE.pattern}")
        body_id = None
    _audit_field(
        f"{path}.body_owner", body.get("body_owner"), "body_owner", None,
        catalog_sources, errors, missing,
    )
    _audit_field(
        f"{path}.body_role", body.get("body_role"), "body_role", None,
        catalog_sources, errors, missing,
    )
    for key in BODY_PROPERTY_FIELDS:
        _audit_field(
            f"{path}.{key}", body.get(key), key, UNITS[key],
            catalog_sources, errors, missing, allow_absent=True,
        )
    role_field = body.get("body_role")
    role = role_field.get("value") if isinstance(role_field, dict) else None
    statuses = {
        key: body[key].get("status") if isinstance(body.get(key), dict) else None
        for key in BODY_PROPERTY_FIELDS
    }
    if role == "virtual_frame":
        for key, status in statuses.items():
            if status != "intentionally_absent":
                errors.append(
                    f"{path}.{key}: virtual_frame must be explicitly intentionally_absent; "
                    "never synthesize geometry, contact, mass or inertia for an intermediate frame"
                )
    elif role == "physical":
        for key in ("mass", "center_of_mass", "inertia"):
            if statuses[key] == "intentionally_absent":
                errors.append(f"{path}.{key}: physical bodies cannot omit dynamic properties")
        collision_status = statuses["collision_geometry"]
        for key in ("contact_friction", "contact_restitution"):
            if collision_status == "intentionally_absent" and statuses[key] != "intentionally_absent":
                errors.append(f"{path}.{key}: must be absent when collision_geometry is absent")
            if collision_status not in {None, "unknown", "intentionally_absent"} and statuses[key] == "intentionally_absent":
                errors.append(f"{path}.{key}: collidable physical bodies require explicit material data")
    visual_field = body.get("visual_geometry")
    visual_value = visual_field.get("value") if isinstance(visual_field, dict) else None
    visuals = visual_value if isinstance(visual_value, list) else [visual_value]
    for visual_index, visual in enumerate(visuals):
        if not isinstance(visual, dict):
            continue
        candidate_id = visual.get("candidate_id")
        if (
            isinstance(candidate_id, str)
            and JOINT_ID_RE.fullmatch(candidate_id)
            and candidate_id not in registered_candidate_ids
        ):
            errors.append(
                f"{path}.visual_geometry.visual[{visual_index}].candidate_id: "
                "not present in the bound asset registry candidates or derived_variants"
            )
            continue
        binding_key = (
            candidate_id, visual.get("artifact_id"), visual.get("object_id")
        )
        binding = registered_visual_bindings.get(binding_key)
        if binding is None:
            errors.append(
                f"{path}.visual_geometry.visual[{visual_index}]: candidate/artifact/object "
                "is not approved for target visual geometry or does not resolve through its "
                "SHA-bound registry manifest"
            )
            continue
        for key in ("file", "sha256", "meters_per_native_unit"):
            if visual.get(key) != binding[key]:
                errors.append(
                    f"{path}.visual_geometry.visual[{visual_index}].{key}: "
                    "does not match the registry manifest binding"
                )
        if binding["meters_per_native_unit"] is None:
            errors.append(
                f"{path}.visual_geometry.visual[{visual_index}]: registry manifest leaves "
                "metric scale unresolved; visual_geometry must remain unknown/absent"
            )
        materials = visual.get("materials")
        if isinstance(materials, dict) and materials.get("mode") == "external":
            errors.append(
                f"{path}.visual_geometry.visual[{visual_index}].materials: external files "
                "are rejected until each dependency is bound by the same SHA-verified registry manifest"
            )
    return body_id


def _polar_radius(samples, azimuth):
    """Periodic-linear radial limit for a structurally validated polar table."""
    angle = azimuth % (2 * math.pi)
    extended = [*samples, [samples[0][0] + 2 * math.pi, samples[0][1]]]
    if angle < samples[0][0]:
        angle += 2 * math.pi
    for left, right in zip(extended, extended[1:]):
        if left[0] <= angle <= right[0]:
            fraction = (angle - left[0]) / (right[0] - left[0])
            return left[1] + fraction * (right[1] - left[1])
    raise ValueError("polar envelope does not cover the full azimuth domain")


def configuration_satisfies_constraint(constraint, coordinates, tolerance=1e-12):
    """Evaluate a validated configuration constraint without simulator defaults."""
    if not isinstance(constraint, dict) or not isinstance(coordinates, (list, tuple)):
        raise ValueError("invalid constraint or coordinates")
    if len(coordinates) != len(constraint.get("joint_ids", [])) or not all(
        _number(coordinate) for coordinate in coordinates
    ):
        raise ValueError("coordinates do not match joint_ids")
    kind = constraint.get("type")
    if kind == "tabulated_polar_envelope":
        if len(coordinates) != 2:
            raise ValueError("polar envelope requires two coordinates")
        center = constraint["center"]
        dx, dy = coordinates[0] - center[0], coordinates[1] - center[1]
        radius = math.hypot(dx, dy)
        if radius <= tolerance:
            return True
        limit = _polar_radius(constraint["samples"], math.atan2(dy, dx))
        return radius <= limit + tolerance
    if kind == "linear_inequality_set":
        for inequality in constraint["inequalities"]:
            value = sum(
                coefficient * coordinate
                for coefficient, coordinate in zip(
                    inequality["coefficients"], coordinates
                )
            )
            if inequality["operator"] == "<=" and value > inequality["bound"] + tolerance:
                return False
            if inequality["operator"] == ">=" and value < inequality["bound"] - tolerance:
                return False
        return True
    raise ValueError(f"unsupported constraint type {kind!r}")


def _audit_configuration_constraints(constraints, joint_info, catalog_sources, errors):
    if not isinstance(constraints, list):
        errors.append("physical_topology.configuration_constraints: must be a list")
        return {}
    constraint_map = {}
    for index, constraint in enumerate(constraints):
        path = f"physical_topology.configuration_constraints[{index}]"
        common_keys = {
            "id", "type", "joint_ids", "frame", "coordinate_units", "evidence",
            "harness", "applicability", "numeric_payload_evidence",
        }
        if not isinstance(constraint, dict):
            errors.append(f"{path}: must be an object")
            continue
        kind = constraint.get("type")
        if kind == "tabulated_polar_envelope":
            expected_keys = common_keys | {
                "center", "azimuth_unit", "radius_unit", "samples", "interpolation",
            }
        elif kind == "linear_inequality_set":
            expected_keys = common_keys | {"inequalities", "bound_unit"}
        else:
            errors.append(f"{path}.type: unsupported configuration constraint")
            expected_keys = common_keys
        if set(constraint) != expected_keys:
            errors.append(f"{path}: fields changed for {kind!r}")
        constraint_id = constraint.get("id")
        if not isinstance(constraint_id, str) or not JOINT_ID_RE.fullmatch(constraint_id):
            errors.append(f"{path}.id: must be a stable lowercase id")
            constraint_id = None
        elif constraint_id in constraint_map:
            errors.append(f"{path}.id: duplicate configuration constraint id")
        if constraint.get("frame") != "joint_coordinate_space":
            errors.append(f"{path}.frame: must be joint_coordinate_space")
        joint_ids = constraint.get("joint_ids")
        if (
            not isinstance(joint_ids, list)
            or not joint_ids
            or len(joint_ids) != len(set(joint_ids))
            or not all(isinstance(item, str) and JOINT_ID_RE.fullmatch(item) for item in joint_ids)
        ):
            errors.append(f"{path}.joint_ids: must be unique stable joint ids")
            joint_ids = []
        coordinate_units = constraint.get("coordinate_units")
        if not isinstance(coordinate_units, list) or len(coordinate_units) != len(joint_ids):
            errors.append(f"{path}.coordinate_units: must align with joint_ids")
            coordinate_units = []
        for joint_index, joint_id in enumerate(joint_ids):
            info = joint_info.get(joint_id)
            if info is None:
                errors.append(f"{path}.joint_ids[{joint_index}]: undefined joint")
                continue
            expected_unit = "m" if info["joint_type"] == "prismatic" else "rad"
            if joint_index >= len(coordinate_units) or coordinate_units[joint_index] != expected_unit:
                errors.append(f"{path}.coordinate_units[{joint_index}]: expected {expected_unit!r}")
        if not _valid_refs(constraint.get("evidence"), catalog_sources):
            errors.append(f"{path}.evidence: missing/invalid")
        _append_harness_errors(f"{path}.harness", constraint.get("harness"), errors)
        if not isinstance(constraint.get("applicability"), str) or not constraint["applicability"].strip():
            errors.append(f"{path}.applicability: missing")

        numeric_payload = (
            {"center": constraint.get("center"), "samples": constraint.get("samples")}
            if kind == "tabulated_polar_envelope"
            else {"inequalities": constraint.get("inequalities")}
            if kind == "linear_inequality_set"
            else {}
        )
        numeric_field = constraint.get("numeric_payload_evidence")
        numeric_missing = []
        _audit_field(
            f"{path}.numeric_payload_evidence", numeric_field,
            "constraint_numeric_payload", "typed_by_constraint_schema",
            catalog_sources, errors, numeric_missing,
        )
        if (
            isinstance(numeric_field, dict)
            and numeric_field.get("value") is not None
            and numeric_field.get("value") != numeric_payload
        ):
            errors.append(
                f"{path}.numeric_payload_evidence: bound payload disagrees with constraint numbers"
            )

        if kind == "tabulated_polar_envelope":
            if len(joint_ids) != 2 or len(coordinate_units) != 2 or len(set(coordinate_units)) != 1:
                errors.append(f"{path}: polar envelope requires two same-unit joint coordinates")
            center = constraint.get("center")
            samples = constraint.get("samples")
            if not _vector(center, 2):
                errors.append(f"{path}.center: must contain two finite coordinates")
            if constraint.get("azimuth_unit") != "rad":
                errors.append(f"{path}.azimuth_unit: must be rad")
            if not coordinate_units or constraint.get("radius_unit") != coordinate_units[0]:
                errors.append(f"{path}.radius_unit: must match the joint coordinate units")
            if constraint.get("interpolation") != "periodic_linear":
                errors.append(f"{path}.interpolation: must be periodic_linear")
            valid_samples = (
                isinstance(samples, list)
                and len(samples) >= 4
                and all(
                    _vector(sample, 2)
                    and 0 <= sample[0] < 2 * math.pi
                    and sample[1] > 0
                    for sample in samples
                )
                and all(samples[i][0] < samples[i + 1][0] for i in range(len(samples) - 1))
            )
            if not valid_samples:
                errors.append(f"{path}.samples: require sorted finite [azimuth_rad, positive_radius] values")
            else:
                circular_gaps = [
                    samples[index + 1][0] - samples[index][0]
                    for index in range(len(samples) - 1)
                ] + [samples[0][0] + 2 * math.pi - samples[-1][0]]
                if max(circular_gaps) > math.pi / 2 + 1e-12:
                    errors.append(f"{path}.samples: azimuth coverage gap exceeds pi/2")
                if _vector(center, 2):
                    for sample_index, (azimuth, radius) in enumerate(samples):
                        point = [
                            center[0] + radius * math.cos(azimuth),
                            center[1] + radius * math.sin(azimuth),
                        ]
                        for coordinate_index, joint_id in enumerate(joint_ids):
                            limits = joint_info.get(joint_id, {}).get("limits")
                            if (
                                isinstance(limits, dict)
                                and _number(limits.get("lower"))
                                and _number(limits.get("upper"))
                                and not limits["lower"] - 1e-12 <= point[coordinate_index] <= limits["upper"] + 1e-12
                            ):
                                errors.append(f"{path}.samples[{sample_index}]: boundary exceeds {joint_id} limits")
        elif kind == "linear_inequality_set":
            if not coordinate_units or len(set(coordinate_units)) != 1:
                errors.append(f"{path}: linear inequalities require same-unit coordinates")
            if not coordinate_units or constraint.get("bound_unit") != coordinate_units[0]:
                errors.append(f"{path}.bound_unit: must match coordinate_units")
            inequalities = constraint.get("inequalities")
            if not isinstance(inequalities, list) or not inequalities:
                errors.append(f"{path}.inequalities: must be a non-empty list")
            else:
                for inequality_index, inequality in enumerate(inequalities):
                    inequality_path = f"{path}.inequalities[{inequality_index}]"
                    if not isinstance(inequality, dict) or set(inequality) != {
                        "coefficients", "operator", "bound"
                    }:
                        errors.append(f"{inequality_path}: fields changed")
                        continue
                    coefficients = inequality.get("coefficients")
                    if not _vector(coefficients, len(joint_ids)) or not any(
                        coefficient != 0 for coefficient in coefficients
                    ):
                        errors.append(f"{inequality_path}.coefficients: invalid")
                    if inequality.get("operator") not in {"<=", ">="}:
                        errors.append(f"{inequality_path}.operator: must be <= or >=")
                    if not _number(inequality.get("bound")):
                        errors.append(f"{inequality_path}.bound: must be finite")
        if constraint_id is not None:
            constraint_map[constraint_id] = constraint
    return constraint_map


def _audit_physical_topology(
    topology, catalog_sources, registered_candidate_ids, registered_visual_bindings,
    errors, missing,
):
    path = "physical_topology"
    expected_keys = {
        "status", "bodies", "configuration_constraints", "evidence", "harness",
        "reason", "applicability", "root_attachment", "self_collision_policy",
    }
    if not isinstance(topology, dict):
        errors.append(f"{path}: missing")
        return set(), "invalid", []
    if set(topology) != expected_keys:
        errors.append(f"{path}: fields changed")
    bodies = topology.get("bodies")
    if not isinstance(bodies, list):
        errors.append(f"{path}.bodies: must be a list")
        bodies = []
    constraints = topology.get("configuration_constraints")
    if not isinstance(constraints, list):
        errors.append(f"{path}.configuration_constraints: must be a list")
        constraints = []
    status = topology.get("status")
    body_missing_start = len(missing)
    body_ids = set()
    for index, body in enumerate(bodies):
        body_id = _audit_body(
            body, index, catalog_sources, registered_candidate_ids,
            registered_visual_bindings, errors, missing,
        )
        if body_id in body_ids:
            errors.append(f"{path}.bodies[{index}].id: duplicate global body id")
        elif body_id is not None:
            body_ids.add(body_id)
    if status == "unknown":
        if not isinstance(topology.get("harness"), str) or not topology.get("harness").strip():
            errors.append(f"{path}.harness: unknown topology requires a non-empty audit locator")
        missing.append(path)
        if bodies:
            errors.append(f"{path}: unknown topology must have an empty body list")
        if constraints:
            errors.append(f"{path}: unknown topology must have an empty constraint list")
        if topology.get("evidence") != [] or topology.get("applicability") is not None:
            errors.append(f"{path}: unknown topology cannot claim evidence/applicability")
        if not isinstance(topology.get("reason"), str) or not topology.get("reason").strip():
            errors.append(f"{path}: undocumented unknown topology")
    elif status in {"partial", "modeled"}:
        _append_harness_errors(f"{path}.harness", topology.get("harness"), errors)
        if not bodies:
            errors.append(f"{path}: {status} topology requires at least one body")
        if not _valid_refs(topology.get("evidence"), catalog_sources):
            errors.append(f"{path}.evidence: missing/invalid")
        if not isinstance(topology.get("applicability"), str) or not topology.get("applicability").strip():
            errors.append(f"{path}.applicability: missing")
        if topology.get("reason") is not None:
            errors.append(f"{path}.reason: known topology must clear the unknown reason")
        if status == "modeled" and len(missing) != body_missing_start:
            errors.append(f"{path}: modeled topology cannot contain unresolved body fields")
    else:
        errors.append(f"{path}.status: must be unknown, partial or modeled")
    return body_ids, status, constraints


def _audit_joint(component, joint, index, body_ids, catalog_sources, errors, missing):
    path = f"{component}.motion_model.joints[{index}]"
    expected_keys = {"id", *JOINT_FIELDS}
    if not isinstance(joint, dict):
        errors.append(f"{path}: joint must be an object")
        return None, [], None, None
    if set(joint) != expected_keys:
        errors.append(f"{path}: joint fields changed")
    joint_id = joint.get("id")
    if not isinstance(joint_id, str) or not JOINT_ID_RE.fullmatch(joint_id):
        errors.append(f"{path}.id: must match {JOINT_ID_RE.pattern}")
        joint_id = None

    endpoints = {}
    for key in ("parent_body", "child_body"):
        item = joint.get(key)
        _audit_field(
            f"{path}.{key}", item, key, None,
            catalog_sources, errors, missing,
        )
        value = item.get("value") if isinstance(item, dict) else None
        endpoints[key] = value
        if value is not None and value not in body_ids:
            errors.append(f"{path}.{key}: references an undefined global body id")
    if endpoints.get("parent_body") is not None and endpoints.get("parent_body") == endpoints.get("child_body"):
        errors.append(f"{path}: parent_body and child_body must differ")

    joint_type_item = joint.get("joint_type")
    joint_type = None
    if isinstance(joint_type_item, dict) and joint_type_item.get("value") in JOINT_TYPES:
        joint_type = joint_type_item["value"]
    _audit_field(
        f"{path}.joint_type", joint_type_item, "joint_type", None,
        catalog_sources, errors, missing,
    )

    actuation_item = joint.get("actuation_mode")
    actuation_mode = (
        actuation_item.get("value")
        if isinstance(actuation_item, dict)
        and actuation_item.get("value") in {"passive", "actuated"}
        else None
    )
    _audit_field(
        f"{path}.actuation_mode", actuation_item, "actuation_mode", None,
        catalog_sources, errors, missing,
    )

    mapped = []
    typed_fields = JOINT_FIELDS[4:]
    for key in typed_fields:
        item = joint.get(key)
        expected_unit = JOINT_UNITS[joint_type][key] if joint_type else None
        if key == "input_mapping" and component == "pair" and expected_unit is not None:
            expected_unit = expected_unit.split("->", 1)[0] + "->physical_event"
        if joint_type is None and isinstance(item, dict) and item.get("value") is not None:
            errors.append(f"{path}.{key}: joint_type must be known before typed joint values")
        _audit_field(
            f"{path}.{key}", item, key, expected_unit,
            catalog_sources, errors, missing, joint_type=joint_type,
            physical_only=component == "pair",
            allow_absent=key in {"actuator_effort_limit", "actuator_velocity_limit"},
        )
        if key == "input_mapping" and isinstance(item, dict):
            value = item.get("value")
            if isinstance(value, dict) and isinstance(value.get("effects"), list):
                mapped.extend(
                    effect.get("channel")
                    for effect in value["effects"]
                    if isinstance(effect, dict) and effect.get("channel") in CANONICAL_CHANNELS
                )
    actuator_fields = ("actuator_effort_limit", "actuator_velocity_limit")
    actuator_statuses = {
        key: joint.get(key, {}).get("status")
        if isinstance(joint.get(key), dict) else None
        for key in actuator_fields
    }
    if actuation_mode == "passive":
        for key, field_status in actuator_statuses.items():
            if field_status != "intentionally_absent":
                errors.append(
                    f"{path}.{key}: passive joints must mark actuator limits intentionally_absent; "
                    "simulator clamps are a separate approximation"
                )
    elif actuation_mode == "actuated":
        for key, field_status in actuator_statuses.items():
            if field_status == "intentionally_absent":
                errors.append(f"{path}.{key}: actuated joints require an evidenced actuator limit")
    limits_item = joint.get("joint_limits")
    limits = limits_item.get("value") if isinstance(limits_item, dict) else None
    if joint_type in {"prismatic", "revolute"} and isinstance(limits, dict):
        lower, upper = limits.get("lower"), limits.get("upper")
        if _number(lower) and _number(upper) and lower < upper:
            restoring_item = joint.get("restoring_curve")
            restoring = restoring_item.get("value") if isinstance(restoring_item, dict) else None
            if isinstance(restoring, dict):
                equilibrium = restoring.get("equilibrium_coordinate")
                branches = restoring.get("branches")
                restoring_points = [
                    point
                    for curve in branches.values()
                    if isinstance(curve, list)
                    for point in curve
                ] if isinstance(branches, dict) else []
                if (
                    (_number(equilibrium) and not lower <= equilibrium <= upper)
                    or any(
                        _vector(point, 2) and not lower <= point[0] <= upper
                        for point in restoring_points
                    )
                ):
                    errors.append(
                        f"{path}.restoring_curve: equilibrium and branch coordinates "
                        "must lie within joint_limits"
                    )
                if isinstance(branches, dict):
                    for branch_name, curve in branches.items():
                        if (
                            isinstance(curve, list)
                            and len(curve) >= 2
                            and _vector(curve[0], 2)
                            and _vector(curve[-1], 2)
                            and (
                                not math.isclose(curve[0][0], lower, rel_tol=0.0, abs_tol=1e-12)
                                or not math.isclose(curve[-1][0], upper, rel_tol=0.0, abs_tol=1e-12)
                            )
                        ):
                            errors.append(
                                f"{path}.restoring_curve.branches.{branch_name}: "
                                "finite joint-limit domain must be covered exactly"
                            )
            mapping_item = joint.get("input_mapping")
            mapping = mapping_item.get("value") if isinstance(mapping_item, dict) else None
            effects = mapping.get("effects") if isinstance(mapping, dict) else None
            if isinstance(mapping, dict) and mapping.get("model") == "analog_monotone" and isinstance(effects, list):
                for effect_index, effect in enumerate(effects):
                    curve = effect.get("curve") if isinstance(effect, dict) else None
                    if isinstance(curve, list) and any(
                        _vector(point, 2) and not lower <= point[0] <= upper for point in curve
                    ):
                        errors.append(
                            f"{path}.input_mapping.effect[{effect_index}]: "
                            "coordinates must lie within joint_limits"
                        )
                    if (
                        isinstance(curve, list)
                        and len(curve) >= 2
                        and _vector(curve[0], 2)
                        and _vector(curve[-1], 2)
                        and (
                            not math.isclose(curve[0][0], lower, rel_tol=0.0, abs_tol=1e-12)
                            or not math.isclose(curve[-1][0], upper, rel_tol=0.0, abs_tol=1e-12)
                        )
                    ):
                        errors.append(
                            f"{path}.input_mapping.effect[{effect_index}]: finite joint-limit "
                            "domain must be covered exactly"
                        )
            elif isinstance(mapping, dict) and mapping.get("model") == "digital_hysteresis":
                domain = mapping.get("coordinate_domain")
                if not (
                    _vector(domain, 2)
                    and math.isclose(domain[0], lower, rel_tol=0.0, abs_tol=1e-12)
                    and math.isclose(domain[1], upper, rel_tol=0.0, abs_tol=1e-12)
                ):
                    errors.append(
                        f"{path}.input_mapping.coordinate_domain: finite joint-limit domain "
                        "must be covered exactly"
                    )
    restoring_item = joint.get("restoring_curve")
    restoring = restoring_item.get("value") if isinstance(restoring_item, dict) else None
    mapping_item = joint.get("input_mapping")
    mapping = mapping_item.get("value") if isinstance(mapping_item, dict) else None
    equilibrium = restoring.get("equilibrium_coordinate") if isinstance(restoring, dict) else None
    neutral = mapping.get("neutral_coordinate") if isinstance(mapping, dict) else None
    if isinstance(restoring, dict) and isinstance(mapping, dict):
        if _number(equilibrium) and _number(neutral) and not math.isclose(
            equilibrium, neutral, rel_tol=0.0, abs_tol=1e-12
        ):
            errors.append(
                f"{path}: input_mapping neutral_coordinate must equal restoring equilibrium_coordinate"
            )
    edge = None
    if endpoints.get("parent_body") in body_ids and endpoints.get("child_body") in body_ids:
        edge = (endpoints["parent_body"], endpoints["child_body"], joint_id)
    info = {
        "joint_type": joint_type,
        "limits": limits,
        "component": component,
        "equilibrium": equilibrium,
        "neutral": neutral,
    } if joint_id is not None else None
    return joint_id, mapped, edge, info


def _audit_configuration_domain(name, domain, catalog_sources, errors):
    path = f"{name}.motion_model.configuration_domain"
    expected_keys = {
        "status", "constraint_ids", "combination", "independent_joint_ids",
        "neutral_configuration", "neutral_configuration_evidence", "approximation",
        "evidence", "harness", "reason",
        "applicability",
    }
    if not isinstance(domain, dict) or set(domain) != expected_keys:
        errors.append(f"{path}: fields changed")
        return "invalid", [], None, [], None
    status = domain.get("status")
    constraint_ids = domain.get("constraint_ids")
    if not isinstance(constraint_ids, list) or len(constraint_ids) != len(set(constraint_ids)) or not all(
        isinstance(item, str) and JOINT_ID_RE.fullmatch(item) for item in constraint_ids
    ):
        errors.append(f"{path}.constraint_ids: must be unique stable ids")
        constraint_ids = []
    independent = domain.get("independent_joint_ids")
    if not isinstance(independent, list) or len(independent) != len(set(independent)) or not all(
        isinstance(item, str) and JOINT_ID_RE.fullmatch(item) for item in independent
    ):
        errors.append(f"{path}.independent_joint_ids: must be unique stable joint ids")
        independent = []
    neutral = domain.get("neutral_configuration")
    if neutral is not None and (
        not isinstance(neutral, dict)
        or not neutral
        or not all(
            isinstance(joint_id, str)
            and JOINT_ID_RE.fullmatch(joint_id)
            and _number(coordinate)
            for joint_id, coordinate in neutral.items()
        )
    ):
        errors.append(f"{path}.neutral_configuration: must map stable joint ids to finite coordinates")
        neutral = None
    neutral_field = domain.get("neutral_configuration_evidence")
    neutral_missing = []
    _audit_field(
        f"{path}.neutral_configuration_evidence", neutral_field,
        "neutral_configuration", "per_joint_coordinate_units",
        catalog_sources, errors, neutral_missing,
    )
    neutral_evidence_value = (
        neutral_field.get("value") if isinstance(neutral_field, dict) else None
    )
    if neutral is None:
        if neutral_evidence_value is not None:
            errors.append(
                f"{path}.neutral_configuration_evidence: cannot bind a missing neutral configuration"
            )
    elif neutral_evidence_value != neutral:
        errors.append(
            f"{path}.neutral_configuration_evidence: bound value disagrees with neutral_configuration"
        )
    if status == "unknown":
        if not isinstance(domain.get("harness"), str) or not domain["harness"].strip():
            errors.append(f"{path}.harness: unknown domain requires a non-empty audit locator")
        if (
            constraint_ids or independent or neutral is not None
            or domain.get("combination") is not None
            or domain.get("approximation") is not None
            or domain.get("evidence") != [] or domain.get("applicability") is not None
        ):
            errors.append(f"{path}: unknown domain cannot claim coverage, neutral, approximation or evidence")
        if not isinstance(domain.get("reason"), str) or not domain["reason"].strip():
            errors.append(f"{path}.reason: missing")
    elif status == "constrained":
        _append_harness_errors(f"{path}.harness", domain.get("harness"), errors)
        if not constraint_ids:
            errors.append(f"{path}: constrained domain requires constraint_ids")
        if domain.get("combination") != "intersection":
            errors.append(f"{path}.combination: constrained domains require intersection")
        if neutral is None:
            errors.append(f"{path}.neutral_configuration: constrained domain requires a feasibility witness")
        if domain.get("approximation") is not None or domain.get("reason") is not None:
            errors.append(f"{path}: constrained domain cannot claim approximation/reason")
        if not _valid_refs(domain.get("evidence"), catalog_sources):
            errors.append(f"{path}.evidence: missing/invalid")
        if not isinstance(domain.get("applicability"), str) or not domain["applicability"].strip():
            errors.append(f"{path}.applicability: missing")
    elif status == "explicit_approximation":
        _append_harness_errors(f"{path}.harness", domain.get("harness"), errors)
        if (
            constraint_ids
            or domain.get("combination") != "cartesian_product"
            or domain.get("approximation") != "independent_joint_limits"
        ):
            errors.append(f"{path}: independent-limit approximation requires cartesian_product and no constraints")
        if neutral is None:
            errors.append(f"{path}.neutral_configuration: approximation requires a feasibility witness")
        if not _valid_refs(domain.get("evidence"), catalog_sources):
            errors.append(f"{path}.evidence: missing/invalid")
        if not isinstance(domain.get("reason"), str) or not domain["reason"].strip():
            errors.append(f"{path}.reason: approximation limitation is missing")
        if not isinstance(domain.get("applicability"), str) or not domain["applicability"].strip():
            errors.append(f"{path}.applicability: missing")
    elif status == "unmodeled":
        _append_harness_errors(f"{path}.harness", domain.get("harness"), errors)
        if (
            constraint_ids or independent or neutral is not None
            or domain.get("combination") is not None
            or domain.get("approximation") is not None
        ):
            errors.append(f"{path}: unmodeled domain cannot claim coverage, neutral or approximation")
        if not _valid_refs(domain.get("evidence"), catalog_sources):
            errors.append(f"{path}.evidence: missing/invalid")
        if not isinstance(domain.get("reason"), str) or not domain["reason"].strip():
            errors.append(f"{path}.reason: missing")
        if not isinstance(domain.get("applicability"), str) or not domain["applicability"].strip():
            errors.append(f"{path}.applicability: missing")
    else:
        errors.append(f"{path}.status: invalid")
    return status, constraint_ids, domain.get("combination"), independent, neutral


def _audit_motion_model(name, model, body_ids, topology_status, catalog_sources, errors, missing):
    path = f"{name}.motion_model"
    expected_keys = {
        "applicability", "configuration_domain", "evidence", "harness", "identity_evidence", "joints",
        "physical_only", "reason", "required_control_effects", "status",
    }
    if not isinstance(model, dict):
        errors.append(f"{path}: missing")
        return "invalid", [], [], [], {}, ("invalid", [], None, [], None)
    if set(model) != expected_keys:
        errors.append(f"{path}: fields changed")
    if model.get("required_control_effects") != _required_effects(name):
        errors.append(f"{path}.required_control_effects: must exactly match canonical control effects")
    if model.get("physical_only") is not (name == "pair"):
        errors.append(f"{path}.physical_only: inconsistent classification")
    expected_identity = ["apple_1708_connect_button", "ifixit_1708_buttons"] if name == "pair" else []
    if model.get("identity_evidence") != expected_identity:
        errors.append(f"{path}.identity_evidence: does not match documented control identity")
    if not _valid_refs(model.get("identity_evidence"), catalog_sources, allow_empty=True):
        errors.append(f"{path}.identity_evidence: invalid reference")
    status = model.get("status")
    joints = model.get("joints")
    if not isinstance(joints, list):
        errors.append(f"{path}.joints: must be a list")
        joints = []
    if status == "unknown":
        if not isinstance(model.get("harness"), str) or not model.get("harness").strip():
            errors.append(f"{path}.harness: unknown model requires a non-empty audit locator")
        missing.append(path)
        if joints:
            errors.append(f"{path}: unknown model must have an empty owned-joint list")
        if model.get("evidence") != [] or model.get("applicability") is not None:
            errors.append(f"{path}: unknown model cannot claim evidence/applicability")
        if not isinstance(model.get("reason"), str) or not model.get("reason").strip():
            errors.append(f"{path}: undocumented unknown model")
    elif status in {"partial", "modeled"}:
        _append_harness_errors(f"{path}.harness", model.get("harness"), errors)
        if topology_status == "unknown":
            errors.append(f"{path}: known model requires a declared physical body topology")
        if not _valid_refs(model.get("evidence"), catalog_sources):
            errors.append(f"{path}.evidence: missing/invalid")
        if not isinstance(model.get("applicability"), str) or not model.get("applicability").strip():
            errors.append(f"{path}.applicability: missing")
        if model.get("reason") is not None:
            errors.append(f"{path}.reason: known model must clear the unknown reason")
        if status == "modeled" and name == "pair" and not joints:
            errors.append(f"{path}: modeled physical-only Pair control requires at least one joint")
    else:
        errors.append(f"{path}.status: must be unknown, partial or modeled")

    domain_result = _audit_configuration_domain(
        name, model.get("configuration_domain"), catalog_sources, errors
    )
    joint_ids, mapped, edges, joint_info = [], [], [], {}
    joint_missing_start = len(missing)
    for index, joint in enumerate(joints):
        joint_id, joint_mapped, edge, info = _audit_joint(
            name, joint, index, body_ids, catalog_sources, errors, missing
        )
        if joint_id is not None:
            joint_ids.append(joint_id)
            joint_info[joint_id] = info
        mapped.extend(joint_mapped)
        if edge is not None:
            edges.append(edge)
    if status == "modeled" and len(missing) != joint_missing_start:
        errors.append(f"{path}: modeled status cannot contain unresolved joint fields")
    if status == "modeled" and len(joints) > 1 and domain_result[0] == "unknown":
        errors.append(
            f"{path}: multi-joint modeled controls require a coupled domain, an explicit approximation, or an explicit unmodeled declaration"
        )
    if status == "unknown" and domain_result[0] != "unknown":
        errors.append(f"{path}: unknown motion model requires an unknown configuration domain")
    return status, joint_ids, mapped, edges, joint_info, domain_result


def _audit_graph(body_ids, edges, topology_status, errors):
    parents = {}
    adjacency = {body_id: [] for body_id in body_ids}
    for parent, child, _joint_id in edges:
        if child in parents:
            errors.append(
                f"physical_topology: body {child!r} has multiple parent joints; no aggregation/constraint semantics exist"
            )
        else:
            parents[child] = parent
        adjacency[parent].append(child)

    visiting, visited = set(), set()

    def visit(body_id):
        if body_id in visiting:
            return False
        if body_id in visited:
            return True
        visiting.add(body_id)
        for child in adjacency.get(body_id, []):
            if not visit(child):
                return False
        visiting.remove(body_id)
        visited.add(body_id)
        return True

    if any(not visit(body_id) for body_id in body_ids if body_id not in visited):
        errors.append("physical_topology: body/joint graph contains a directed cycle")
    if topology_status == "modeled" and body_ids:
        roots = body_ids - set(parents)
        if len(roots) != 1 or len(edges) != len(body_ids) - 1:
            errors.append(
                "physical_topology: modeled graph must be one connected rooted tree with every body used exactly once"
            )


def _audit_instance_policies(topology, body_ids, edges, topology_status,
                             catalog_sources, errors, missing):
    root = topology.get("root_attachment") if isinstance(topology, dict) else None
    root_path = "physical_topology.root_attachment"
    root_keys = {
        "status", "mode", "root_body", "reference_frame", "pose", "pose_unit",
        "pose_evidence", "evidence", "harness", "reason", "applicability",
    }
    if not isinstance(root, dict) or set(root) != root_keys:
        errors.append(f"{root_path}: fields changed")
        root = {}
    root_status = root.get("status")
    pose_field = root.get("pose_evidence")
    pose_missing = []
    _audit_field(
        f"{root_path}.pose_evidence", pose_field, "root_pose", "m,rad",
        catalog_sources, errors, pose_missing,
    )
    pose_evidence_value = (
        pose_field.get("value") if isinstance(pose_field, dict) else None
    )
    if root.get("pose") is None:
        if pose_evidence_value is not None:
            errors.append(f"{root_path}.pose_evidence: cannot bind a missing pose")
    elif pose_evidence_value != root.get("pose"):
        errors.append(f"{root_path}.pose_evidence: bound value disagrees with pose")
    if root_status == "unknown":
        if not isinstance(root.get("harness"), str) or not root.get("harness", "").strip():
            errors.append(f"{root_path}.harness: unknown attachment requires an audit locator")
        missing.append(root_path)
        if any(root.get(key) is not None for key in ("mode", "root_body", "reference_frame", "pose")):
            errors.append(f"{root_path}: unknown attachment cannot claim a mode or pose")
        if root.get("evidence") != [] or root.get("applicability") is not None:
            errors.append(f"{root_path}: unknown attachment cannot claim evidence/applicability")
        if not isinstance(root.get("reason"), str) or not root["reason"].strip():
            errors.append(f"{root_path}.reason: missing")
    elif root_status == "modeled":
        _append_harness_errors(f"{root_path}.harness", root.get("harness"), errors)
        if root.get("mode") not in {"fixed_to_fixture", "free_dynamic", "kinematic"}:
            errors.append(f"{root_path}.mode: invalid")
        if root.get("root_body") not in body_ids:
            errors.append(f"{root_path}.root_body: undefined")
        graph_children = {child for _parent, child, _joint in edges}
        graph_roots = body_ids - graph_children
        if len(graph_roots) == 1 and root.get("root_body") not in graph_roots:
            errors.append(f"{root_path}.root_body: must be the articulation graph root")
        if root.get("reference_frame") not in {"world", "fixture"}:
            errors.append(f"{root_path}.reference_frame: must be world or fixture")
        if root.get("pose_unit") != "m,rad" or not (
            isinstance(root.get("pose"), dict)
            and set(root["pose"]) == {"xyz", "rpy"}
            and _vector(root["pose"].get("xyz"), 3)
            and _vector(root["pose"].get("rpy"), 3)
        ):
            errors.append(f"{root_path}.pose: must be a finite reference-frame pose in m,rad")
        if not _valid_refs(root.get("evidence"), catalog_sources):
            errors.append(f"{root_path}.evidence: missing/invalid")
        if root.get("reason") is not None:
            errors.append(f"{root_path}.reason: modeled attachment must clear unknown reason")
        if not isinstance(root.get("applicability"), str) or not root["applicability"].strip():
            errors.append(f"{root_path}.applicability: missing")

        root_actor = {
            "fixed_to_fixture": ("rigid_static", "static"),
            "kinematic": ("rigid_kinematic", "kinematic"),
            "free_dynamic": ("rigid_dynamic", "dynamic"),
        }.get(root.get("mode"))
        # A fixed-base reduced-coordinate articulation is not a static actor:
        # eFIX_BASE fixes its root link, while every PxArticulationLink remains a
        # non-kinematic articulation link.  Only a standalone fixed body is static.
        articulation_actor = ("articulation_link_nonkinematic", "dynamic")
        bodies = topology.get("bodies", []) if isinstance(topology, dict) else []
        for body_index, body in enumerate(bodies if isinstance(bodies, list) else []):
            if not isinstance(body, dict):
                continue
            expected_actor = articulation_actor if edges else root_actor
            collision_field = body.get("collision_geometry")
            collision_value = (
                collision_field.get("value") if isinstance(collision_field, dict) else None
            )
            colliders = collision_value if isinstance(collision_value, list) else [collision_value]
            for collider_index, collider in enumerate(colliders):
                if not isinstance(collider, dict) or collider.get("type") not in {"mesh", "convex_mesh"}:
                    continue
                backend = collider.get("backend_shape")
                declared = (
                    (backend.get("actor_kind"), backend.get("actor_mobility"))
                    if isinstance(backend, dict)
                    else (None, None)
                )
                if expected_actor is not None and declared != expected_actor:
                    errors.append(
                        f"physical_topology.bodies[{body_index}].collision_geometry."
                        f"collider[{collider_index}].backend_shape actor: must be "
                        f"kind={expected_actor[0]!r}, mobility={expected_actor[1]!r} "
                        "for this body; a fixed articulation root is not a rigid static actor"
                    )
    else:
        errors.append(f"{root_path}.status: must be unknown or modeled")

    policy = topology.get("self_collision_policy") if isinstance(topology, dict) else None
    policy_path = "physical_topology.self_collision_policy"
    policy_keys = {
        "status", "default", "pair_overrides", "evidence", "harness", "reason",
        "applicability",
    }
    if not isinstance(policy, dict) or set(policy) != policy_keys:
        errors.append(f"{policy_path}: fields changed")
        policy = {}
    policy_status = policy.get("status")
    overrides = policy.get("pair_overrides")
    if not isinstance(overrides, list):
        errors.append(f"{policy_path}.pair_overrides: must be a list")
        overrides = []
    if policy_status == "unknown":
        if not isinstance(policy.get("harness"), str) or not policy.get("harness", "").strip():
            errors.append(f"{policy_path}.harness: unknown policy requires an audit locator")
        missing.append(policy_path)
        if policy.get("default") is not None or overrides:
            errors.append(f"{policy_path}: unknown policy cannot claim defaults/overrides")
        if policy.get("evidence") != [] or policy.get("applicability") is not None:
            errors.append(f"{policy_path}: unknown policy cannot claim evidence/applicability")
        if not isinstance(policy.get("reason"), str) or not policy["reason"].strip():
            errors.append(f"{policy_path}.reason: missing")
    elif policy_status == "modeled":
        _append_harness_errors(f"{policy_path}.harness", policy.get("harness"), errors)
        if policy.get("default") not in {"enabled", "disabled"}:
            errors.append(f"{policy_path}.default: must be enabled or disabled")
        if not _valid_refs(policy.get("evidence"), catalog_sources):
            errors.append(f"{policy_path}.evidence: missing/invalid")
        if policy.get("reason") is not None:
            errors.append(f"{policy_path}.reason: modeled policy must clear unknown reason")
        if not isinstance(policy.get("applicability"), str) or not policy["applicability"].strip():
            errors.append(f"{policy_path}.applicability: missing")
        seen_pairs = set()
        for index, override in enumerate(overrides):
            override_path = f"{policy_path}.pair_overrides[{index}]"
            if not isinstance(override, dict) or set(override) != {"body_a", "body_b", "enabled"}:
                errors.append(f"{override_path}: fields changed")
                continue
            body_a, body_b = override.get("body_a"), override.get("body_b")
            if body_a not in body_ids or body_b not in body_ids or body_a == body_b:
                errors.append(f"{override_path}: must reference two distinct bodies")
            pair = tuple(sorted((str(body_a), str(body_b))))
            if pair in seen_pairs:
                errors.append(f"{override_path}: duplicate body pair")
            seen_pairs.add(pair)
            if type(override.get("enabled")) is not bool:
                errors.append(f"{override_path}.enabled: must be boolean")

        override_modes = {
            tuple(sorted((override.get("body_a"), override.get("body_b")))):
                override.get("enabled")
            for override in overrides
            if isinstance(override, dict)
            and override.get("body_a") in body_ids
            and override.get("body_b") in body_ids
            and override.get("body_a") != override.get("body_b")
            and type(override.get("enabled")) is bool
        }
        edge_pairs = {
            tuple(sorted((parent, child)))
            for parent, child, _joint_id in edges
        }
        for pair in sorted(edge_pairs):
            desired = override_modes.get(pair, policy.get("default") == "enabled")
            if desired:
                errors.append(
                    f"{policy_path}: direct parent-child pair {pair} cannot be enabled; "
                    "PhysX articulation links suppress adjacent-link collision internally "
                    "regardless of the shape filter"
                )
        body_filters = {}
        bodies = topology.get("bodies", []) if isinstance(topology, dict) else []
        for body in bodies if isinstance(bodies, list) else []:
            if not isinstance(body, dict) or body.get("id") not in body_ids:
                continue
            field = body.get("collision_geometry")
            value = field.get("value") if isinstance(field, dict) else None
            colliders = value if isinstance(value, list) else [value]
            filters = [
                collider.get("collision_filter")
                for collider in colliders
                if isinstance(collider, dict)
                and (
                    collider.get("type") not in {"mesh", "convex_mesh"}
                    or (
                        isinstance(collider.get("backend_shape"), dict)
                        and collider["backend_shape"].get("simulation_role")
                        == "simulation_and_query"
                    )
                )
                and not _collision_filter_errors(collider.get("collision_filter"))
            ]
            body_filters[body["id"]] = filters
        collision_body_ids = sorted(body_filters)
        for first_index, first_id in enumerate(collision_body_ids):
            for second_id in collision_body_ids[first_index + 1:]:
                pair = (first_id, second_id)
                desired = override_modes.get(
                    pair, policy.get("default") == "enabled"
                )
                allowed = any(
                    _sapien_filters_allow(first_filter, second_filter)
                    for first_filter in body_filters[first_id]
                    for second_filter in body_filters[second_id]
                )
                effective_allowed = allowed and pair not in edge_pairs
                if desired != effective_allowed:
                    errors.append(
                        f"{policy_path}: declared self-collision {desired} for {pair} "
                        "contradicts the effective backend result "
                        f"(shape_filter_allow={allowed}, adjacent_link_backend_block="
                        f"{pair in edge_pairs}, effective_allow={effective_allowed})"
                    )
    else:
        errors.append(f"{policy_path}.status: must be unknown or modeled")
    if topology_status == "modeled" and (root_status != "modeled" or policy_status != "modeled"):
        errors.append(
            "physical_topology: modeled topology requires explicit root attachment and self-collision policy"
        )


def _artifact_hash_verification(spec, artifact_root=None):
    items = []
    resolved_root = Path(artifact_root).resolve() if artifact_root is not None else None

    def add_artifact(filename, expected, role):
        record = {
            "role": role,
            "file": filename,
            "exists_at_artifact_root": None,
            "sha256_matches": None,
        }
        if resolved_root is not None and _safe_relative_asset_path(filename):
            local = (resolved_root / filename).resolve()
            inside_root = local == resolved_root or resolved_root in local.parents
            record["exists_at_artifact_root"] = inside_root and local.is_file()
            if record["exists_at_artifact_root"]:
                digest = hashlib.sha256()
                try:
                    with local.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                    record["sha256_matches"] = digest.hexdigest() == expected
                except OSError:
                    record["sha256_matches"] = False
        items.append(record)

    topology = spec.get("physical_topology", {}) if isinstance(spec, dict) else {}
    bodies = topology.get("bodies", []) if isinstance(topology, dict) else []
    for body in bodies if isinstance(bodies, list) else []:
        if not isinstance(body, dict):
            continue
        visual_field = body.get("visual_geometry")
        visual_value = visual_field.get("value") if isinstance(visual_field, dict) else None
        visuals = visual_value if isinstance(visual_value, list) else [visual_value]
        for visual in visuals:
            if not isinstance(visual, dict):
                continue
            add_artifact(visual.get("file"), visual.get("sha256"), "visual_mesh")
            materials = visual.get("materials")
            files = materials.get("files", []) if isinstance(materials, dict) else []
            for material_file in files if isinstance(files, list) else []:
                if isinstance(material_file, dict):
                    add_artifact(
                        material_file.get("file"), material_file.get("sha256"),
                        "visual_material_dependency",
                    )
        field = body.get("collision_geometry")
        value = field.get("value") if isinstance(field, dict) else None
        colliders = value if isinstance(value, list) else [value]
        for collider in colliders:
            if not isinstance(collider, dict) or collider.get("type") not in {"mesh", "convex_mesh"}:
                continue
            add_artifact(collider.get("file"), collider.get("sha256"), "collision_mesh")
            backend_shape = collider.get("backend_shape")
            sdf = (
                backend_shape.get("sdf_artifact")
                if isinstance(backend_shape, dict)
                else None
            )
            if isinstance(sdf, dict):
                add_artifact(sdf.get("file"), sdf.get("sha256"), "collision_sdf")
    if not items:
        status = "not_applicable"
    elif all(item["sha256_matches"] is True for item in items):
        status = "verified"
    else:
        status = "unverified"
    return {
        "status": status,
        "artifact_root": str(resolved_root) if resolved_root is not None else None,
        "items": items,
    }


def audit(spec, catalog, artifact_root=None, asset_registry=None):
    errors, missing = [], []
    catalog_sources = catalog.get("sources") if isinstance(catalog, dict) else None
    if not isinstance(catalog_sources, dict):
        errors.append("catalog: sources must be an object")
        catalog_sources = {}
    try:
        asset_registry = _load_asset_registry(asset_registry)
        report_asset_registry_sha256 = _document_sha256(asset_registry)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        asset_registry = None
        report_asset_registry_sha256 = None
        errors.append(f"asset registry: could not load a finite JSON document ({exc})")
    registered_candidate_ids, registered_visual_bindings = _registered_visual_bindings(
        asset_registry, catalog_sources, errors
    )
    _audit_viewer_adapter_gate(asset_registry, errors)
    try:
        report_spec_sha256 = _document_sha256(spec)
    except (TypeError, ValueError):
        report_spec_sha256 = None
    try:
        report_catalog_sha256 = _catalog_sha256(catalog)
    except (TypeError, ValueError):
        report_catalog_sha256 = None
    if not isinstance(spec, dict):
        return {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "spec_sha256": report_spec_sha256,
            "catalog_sha256": report_catalog_sha256,
            "asset_registry_sha256": report_asset_registry_sha256,
            "hash_encoding": "sha256(json.dumps(document, sort_keys=True, allow_nan=False).encode())",
            "schema_errors": [*errors, "specification root must be an object"],
            "unresolved_fields": [],
            "schema_valid": False,
            "artifact_hash_verification": {
                "status": "not_applicable",
                "artifact_root": str(Path(artifact_root).resolve()) if artifact_root is not None else None,
                "items": [],
            },
            "readiness_blockers": [{
                "id": "invalid_specification",
                "detail": "Schema validation did not run on a valid specification object.",
            }],
            "dynamics_ready": False,
            "readiness_reason": "No simulator/contact validation has been performed; schema completeness alone never enables dynamics.",
        }
    if type(spec.get("schema_version")) is not int or spec.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: expected integer {SCHEMA_VERSION}, got {spec.get('schema_version')!r}")
    try:
        expected_hash = _catalog_sha256(catalog)
        generated = (
            make_spec(catalog, asset_registry=asset_registry)
            if asset_registry is not None
            else None
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        errors.append("catalog or asset registry: must contain finite JSON values")
        expected_hash = None
        generated = None
    if expected_hash is None or spec.get("catalog_sha256") != expected_hash:
        errors.append("source catalog hash mismatch")
    if generated is not None:
        if set(spec) != set(generated):
            errors.append("specification top-level fields changed")
        immutable = (
            "hardware_revision", "status", "component_inventory_basis", "input_schema",
            "asset_registry_binding", "physical_only_controls", "reference_candidates", "reference_policy",
            "evidence_field_policy",
            "frame_convention", "topology_policy", "dpad_policy", "stick_policy", "trigger_policy",
            "mesh_unit_policy", "curve_policy", "configuration_constraint_policy",
            "simulator_policy", "contact_material_policy", "interactive_adapter_gate",
            "excluded_visual_controls",
        )
        for key in immutable:
            if spec.get(key) != generated[key]:
                errors.append(f"{key}: canonical metadata changed")
    if "w3c_gamepad_standard_mapping" not in catalog_sources:
        errors.append("input_schema: W3C standard mapping evidence is absent from catalog")
    if "physx_material" not in catalog_sources:
        errors.append("contact_material_policy: PhysX material evidence is absent from catalog")
    for source_id in (
        "physx_shape_offsets", "sapien_collision_groups", "physx_rigid_body_collision"
    ):
        if source_id not in catalog_sources:
            errors.append(f"simulator_policy: {source_id} evidence is absent from catalog")
    target_hardware = asset_registry.get("target_hardware") if isinstance(asset_registry, dict) else None
    hardware_revision = spec.get("hardware_revision")
    spec_revision = hardware_revision.get("value") if isinstance(hardware_revision, dict) else None
    if not isinstance(target_hardware, dict) or (
        target_hardware.get("model") != "Xbox One Wireless Controller"
        or target_hardware.get("revision") != spec_revision
        or spec_revision != "1708"
    ):
        errors.append(
            "asset registry: target model/revision must match canonical Xbox One Wireless "
            "Controller 1708 specification"
        )

    body_ids, topology_status, constraints = _audit_physical_topology(
        spec.get("physical_topology"), catalog_sources, registered_candidate_ids,
        registered_visual_bindings,
        errors, missing,
    )
    parts = spec.get("parts")
    if not isinstance(parts, dict) or set(parts) != set(CONTROLS):
        errors.append("component coverage changed")
    all_joint_ids = set()
    all_mapped = []
    all_edges = []
    all_joint_info = {}
    component_status = {}
    component_joint_ids = {}
    component_domains = {}
    component_mapped = {}
    for name in CONTROLS:
        fields = parts.get(name, {}) if isinstance(parts, dict) else {}
        if not isinstance(fields, dict) or set(fields) != {"motion_model"}:
            errors.append(f"{name}: logical component must contain only motion_model")
            fields = fields if isinstance(fields, dict) else {}
        status, joint_ids, mapped, edges, joint_info, domain = _audit_motion_model(
            name, fields.get("motion_model"), body_ids, topology_status,
            catalog_sources, errors, missing,
        )
        component_status[name] = status
        component_joint_ids[name] = set(joint_ids)
        component_domains[name] = domain
        component_mapped[name] = list(mapped)
        for joint_id in joint_ids:
            if joint_id in all_joint_ids:
                errors.append(f"{name}.motion_model: duplicate global joint id {joint_id!r}")
            all_joint_ids.add(joint_id)
            if joint_id in joint_info:
                all_joint_info[joint_id] = joint_info[joint_id]
        all_mapped.extend(mapped)
        all_edges.extend(edges)

    _audit_graph(body_ids, all_edges, topology_status, errors)
    _audit_instance_policies(
        spec.get("physical_topology"), body_ids, all_edges, topology_status,
        catalog_sources, errors, missing,
    )
    constraint_map = _audit_configuration_constraints(
        constraints, all_joint_info, catalog_sources, errors
    )
    referenced_constraints = set()
    for name, domain in component_domains.items():
        domain_status, constraint_ids, combination, independent_ids, neutral = domain
        owned = component_joint_ids.get(name, set())
        domain_path = f"{name}.motion_model.configuration_domain"
        constrained_joints = set()
        resolved_constraints = []
        if domain_status == "constrained":
            for constraint_id in constraint_ids:
                constraint = constraint_map.get(constraint_id)
                if constraint is None:
                    errors.append(f"{domain_path}: undefined constraint {constraint_id!r}")
                    continue
                referenced_constraints.add(constraint_id)
                constraint_joints = set(constraint.get("joint_ids", []))
                constrained_joints.update(constraint_joints)
                resolved_constraints.append(constraint)
                if not constraint_joints <= owned:
                    errors.append(
                        f"{domain_path}: constraint {constraint_id!r} references a joint "
                        "owned by another logical control"
                    )
            independent_set = set(independent_ids)
            if constrained_joints & independent_set:
                errors.append(f"{domain_path}: constrained and independent joints must not overlap")
            if constrained_joints | independent_set != owned:
                errors.append(
                    f"{domain_path}: constraint joints plus independent_joint_ids must "
                    "cover every owned joint exactly"
                )
        elif domain_status == "explicit_approximation":
            if set(independent_ids) != owned:
                errors.append(
                    f"{domain_path}: independent-limit approximation must list every owned joint"
                )

        if domain_status in {"constrained", "explicit_approximation"}:
            if not isinstance(neutral, dict) or set(neutral) != owned:
                errors.append(f"{domain_path}: neutral_configuration must cover every owned joint")
            else:
                for joint_id, coordinate in neutral.items():
                    info = all_joint_info.get(joint_id, {})
                    limits = info.get("limits")
                    if isinstance(limits, dict) and not limits.get("unbounded") and not (
                        _number(limits.get("lower"))
                        and _number(limits.get("upper"))
                        and limits["lower"] <= coordinate <= limits["upper"]
                    ):
                        errors.append(f"{domain_path}: neutral {joint_id!r} lies outside joint limits")
                    for source_name in ("equilibrium", "neutral"):
                        expected = info.get(source_name)
                        if _number(expected) and not math.isclose(
                            coordinate, expected, rel_tol=0.0, abs_tol=1e-12
                        ):
                            errors.append(
                                f"{domain_path}: neutral {joint_id!r} disagrees with joint {source_name}"
                            )
                for constraint in resolved_constraints:
                    joint_ids = constraint.get("joint_ids", [])
                    if all(joint_id in neutral for joint_id in joint_ids):
                        try:
                            feasible = configuration_satisfies_constraint(
                                constraint, [neutral[joint_id] for joint_id in joint_ids]
                            )
                        except (KeyError, TypeError, ValueError):
                            feasible = False
                        if not feasible:
                            errors.append(
                                f"{domain_path}: neutral_configuration violates constraint "
                                f"{constraint.get('id')!r}; the declared intersection has no feasibility witness"
                            )
    unused_constraints = set(constraint_map) - referenced_constraints
    if unused_constraints:
        errors.append(
            "physical_topology.configuration_constraints: unreferenced constraints "
            f"{sorted(unused_constraints)}"
        )

    counts = {channel: all_mapped.count(channel) for channel in CANONICAL_CHANNELS}
    duplicates = sorted(channel for channel, count in counts.items() if count > 1)
    if duplicates:
        errors.append(
            "input_mapping: duplicate channel mappings require an explicit aggregation schema; "
            f"none is defined for {duplicates}"
        )
    for name, required in CONTROL_EFFECTS.items():
        local = component_mapped.get(name, [])
        foreign = sorted(set(local) - set(required))
        if foreign:
            errors.append(
                f"{name}.motion_model: maps channels owned by another logical control {foreign}"
            )
        if component_status.get(name) == "modeled":
            local_counts = {channel: local.count(channel) for channel in required}
            if (
                any(count != 1 for count in local_counts.values())
                or len(local) != len(required)
            ):
                errors.append(
                    f"{name}.motion_model: modeled mapping must contain each of its own "
                    "logical effects exactly once"
                )
        if component_status.get(name) == "unknown" and local:
            errors.append(f"{name}.motion_model: mapped effects contradict unknown status")

    represented = [channel for name in CONTROL_EFFECTS for channel in CONTROL_EFFECTS[name]]
    if len(represented) != len(set(represented)) or set(represented) != set(CANONICAL_CHANNELS):
        errors.append("internal schema: control effect coverage is not exactly the canonical 21 channels")
    artifact_verification = _artifact_hash_verification(spec, artifact_root)
    readiness_blockers = [
        {
            "id": "unresolved_physical_fields",
            "count": len(missing),
            "detail": "Unknown target topology, mechanism or material fields remain explicit.",
        },
        {
            "id": "canonical_viewer_adapter_unimplemented",
            "detail": "The schema-v2 to interactive-viewer adapter remains fail-closed.",
        },
        {
            "id": "simulator_contact_validation_missing",
            "detail": "No Xbox 1708 simulator/contact validation run is bound to this specification.",
        },
        {
            "id": "physics_cooking_parameters_unresolved",
            "detail": "Raw mesh declarations do not yet bind an exact PhysX version and complete PxCookingParams, or a SHA-bound pre-cooked binary with a no-recook contract; no backend default may be used for export.",
        },
    ]
    sapien_source = catalog_sources.get("sapien_collision_groups", {})
    if not isinstance(sapien_source, dict) or not str(
        sapien_source.get("verification_status", "")
    ).startswith("automated_primary_page_fetch_verified"):
        readiness_blockers.append({
            "id": "sapien_collision_filter_source_verification_pending",
            "detail": "The exact primary SAPIEN collision-filter page was recorded, but automated fetch verification timed out in this run.",
        })
    if artifact_verification["status"] == "unverified":
        readiness_blockers.append({
            "id": "external_artifact_hashes_unverified",
            "detail": "At least one external visual/collision/SDF artifact was not verified against the supplied artifact root.",
        })
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "spec_sha256": report_spec_sha256,
        "catalog_sha256": report_catalog_sha256,
        "asset_registry_sha256": report_asset_registry_sha256,
        "hash_encoding": "sha256(json.dumps(document, sort_keys=True, allow_nan=False).encode())",
        "schema_errors": errors,
        "unresolved_fields": missing,
        "schema_valid": not errors,
        "artifact_hash_verification": artifact_verification,
        "readiness_blockers": readiness_blockers,
        "dynamics_ready": False,
        "readiness_reason": "Schema validity covers structure and evidence only. The current instance has no validated simulator/contact model, and external mesh hashes may be unverified when assets are stored off-node.",
    }


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["generate", "sync-spec", "audit", "require-dynamics"]
    )
    parser.add_argument("--output", type=Path, help="write a full audit to a non-canonical path")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        help="resolve safe relative mesh paths here and verify their declared SHA256",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="explicitly replace the canonical spec (sync-spec) or reviewed audit (audit)",
    )
    args = parser.parse_args()
    if args.publish and args.output is not None:
        parser.error("--publish and --output are mutually exclusive")
    if args.command in {"generate", "sync-spec"} and args.output is not None:
        parser.error(f"{args.command} does not emit an audit artifact")
    if args.command in {"generate", "sync-spec"} and args.artifact_root is not None:
        parser.error(f"{args.command} does not inspect external artifacts")
    if args.command == "generate" and args.publish:
        parser.error("use sync-spec --publish to replace an existing canonical specification")

    catalog = json.loads((ROOT / "sources/catalog.json").read_text())
    path = ROOT / "specs/xbox_v1.json"
    generated = make_spec(catalog)
    if args.command == "generate":
        if path.exists():
            raise SystemExit("Refusing to overwrite existing specification.")
        _atomic_json(path, generated)
        return
    if args.command == "sync-spec":
        current = json.loads(path.read_text()) if path.exists() else None
        try:
            synchronized, candidate_report = validated_synchronize_spec(current, catalog)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        in_sync = current == synchronized
        if candidate_report["schema_errors"]:
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "in_sync": False,
                "schema_valid": False,
                "schema_errors": candidate_report["schema_errors"],
            }, indent=2))
            raise SystemExit(2)
        if args.publish:
            _atomic_json(path, synchronized)
            in_sync = True
        print(json.dumps({"schema_version": SCHEMA_VERSION, "in_sync": in_sync}, indent=2))
        if not in_sync:
            raise SystemExit(2)
        return

    spec = json.loads(path.read_text())
    report = audit(spec, catalog, artifact_root=args.artifact_root)
    published = ROOT / "results/spec_audit.json"
    output = published if args.publish else args.output
    if output is not None:
        output = output.resolve()
        if output == published.resolve() and not args.publish:
            parser.error("refusing to overwrite results/spec_audit.json without --publish")
        _atomic_json(output, report)
    print(json.dumps({
        "schema_valid": report["schema_valid"],
        "unresolved_count": len(report["unresolved_fields"]),
        "dynamics_ready": report["dynamics_ready"],
        "artifact_hash_status": report["artifact_hash_verification"]["status"],
    }, indent=2))
    if report["schema_errors"] or args.command == "require-dynamics":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
