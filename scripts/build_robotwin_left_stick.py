"""Build the evidence-bound RoboTwin/SAPIEN left-stick vertical slice."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from build_kinematics import build as build_kinematics


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "references" / "left_stick.json"
VISUAL_MANIFEST = (
    ROOT
    / "build"
    / "resources"
    / "common"
    / "xbox_one_s"
    / "visual"
    / "manifest.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "build"
    / "standalone"
    / "robotwin"
    / "left_stick"
)


def _fmt(value: float) -> str:
    return f"{value:.12g}"


def _vec(values: list[float] | tuple[float, ...]) -> str:
    return " ".join(_fmt(float(value)) for value in values)


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _origin(parent: ET.Element, xyz: tuple[float, float, float], rpy=(0.0, 0.0, 0.0)) -> None:
    ET.SubElement(parent, "origin", xyz=_vec(xyz), rpy=_vec(rpy))


def _inertial(
    link: ET.Element,
    mass: float,
    com: tuple[float, float, float],
    diagonal: tuple[float, float, float],
) -> None:
    inertial = ET.SubElement(link, "inertial")
    _origin(inertial, com)
    ET.SubElement(inertial, "mass", value=_fmt(mass))
    ET.SubElement(
        inertial,
        "inertia",
        ixx=_fmt(diagonal[0]),
        ixy="0",
        ixz="0",
        iyy=_fmt(diagonal[1]),
        iyz="0",
        izz=_fmt(diagonal[2]),
    )


def _box_collision(
    link: ET.Element,
    name: str,
    xyz: tuple[float, float, float],
    size: tuple[float, float, float],
    yaw: float = 0.0,
) -> None:
    collision = ET.SubElement(link, "collision", name=name)
    _origin(collision, xyz, (0.0, 0.0, yaw))
    geometry = ET.SubElement(collision, "geometry")
    ET.SubElement(geometry, "box", size=_vec(size))


def _cylinder_collision(
    link: ET.Element,
    name: str,
    center_z: float,
    radius: float,
    length: float,
) -> None:
    collision = ET.SubElement(link, "collision", name=name)
    _origin(collision, (0.0, 0.0, center_z))
    geometry = ET.SubElement(collision, "geometry")
    ET.SubElement(geometry, "cylinder", radius=_fmt(radius), length=_fmt(length))


def _joint(
    robot: ET.Element,
    name: str,
    parent: str,
    child: str,
    origin: tuple[float, float, float],
    axis: tuple[float, float, float],
    limit: float,
    effort: float,
    velocity: float,
    damping: float,
    friction: float,
) -> None:
    joint = ET.SubElement(robot, "joint", name=name, type="revolute")
    _origin(joint, origin)
    ET.SubElement(joint, "parent", link=parent)
    ET.SubElement(joint, "child", link=child)
    ET.SubElement(joint, "axis", xyz=_vec(axis))
    ET.SubElement(
        joint,
        "limit",
        lower=_fmt(-limit),
        upper=_fmt(limit),
        effort=_fmt(effort),
        velocity=_fmt(velocity),
    )
    ET.SubElement(joint, "dynamics", damping=_fmt(damping), friction=_fmt(friction))


def _find_joint(profile: dict, joint_id: str) -> dict:
    for joint in profile.get("joints", []):
        if joint.get("id") == joint_id:
            return joint
    raise ValueError(f"missing kinematic joint {joint_id!r}")


def build(output: Path, *, kinematics: Path | None = None,
          visual_manifest: Path = VISUAL_MANIFEST) -> None:
    source = _json(SOURCE)
    kinematics = _json(kinematics) if kinematics is not None else build_kinematics()[1]
    visual = _json(visual_manifest)
    output.mkdir(parents=True, exist_ok=True)
    (output / "collision").mkdir(exist_ok=True)
    (output / "visual").mkdir(exist_ok=True)

    k = source["kinematics"]
    dynamics = source["passive_dynamics"]
    mass = source["mass_properties"]
    collision = source["collision_geometry"]
    contact = source["contact_material"]

    source_x = _find_joint(kinematics, "left_stick_x")
    source_y = _find_joint(kinematics, "left_stick_y")
    if source_x["pivot_source_m"] != k["pivot_m_source_frame"]:
        raise ValueError("left-stick pivot differs from the reviewed kinematic profile")
    if source_x["axis_source"] != k["horizontal_axis_source_frame"]:
        raise ValueError("left-stick horizontal axis differs from evidence")
    if source_y["axis_source"] != k["vertical_axis_source_frame"]:
        raise ValueError("left-stick vertical axis differs from evidence")
    if not math.isclose(source_x["limits"][1], k["half_sweep_rad"], abs_tol=1e-12):
        raise ValueError("left-stick angle differs from the reviewed kinematic profile")

    robot = ET.Element("robot", name="xbox_one_s_left_stick")
    body = ET.SubElement(robot, "link", name="controller_body")
    _inertial(
        body,
        mass["body_link_mass_kg"],
        (-0.00014, -0.00325, -0.00475),
        tuple(mass["body_inertia_kg_m2"]),
    )
    _box_collision(body, "body_central_support", (0.0, 0.0, -0.018), (0.12, 0.075, 0.028))

    pivot = tuple(float(v) for v in k["pivot_m_source_frame"])
    gate = collision["gate"]
    count = int(gate["segments"])
    inner = float(gate["inner_radius_m"])
    outer = float(gate["outer_radius_m"])
    center_radius = 0.5 * (inner + outer)
    radial_size = outer - inner
    tangential_size = 2.0 * inner * math.tan(math.pi / count)
    for index in range(count):
        theta = 2.0 * math.pi * index / count
        center = (
            pivot[0] + center_radius * math.cos(theta),
            pivot[1] + center_radius * math.sin(theta),
            pivot[2] + float(gate["center_z_m"]),
        )
        _box_collision(
            body,
            f"left_stick_gate_{index:02d}",
            center,
            (radial_size, tangential_size, float(gate["height_m"])),
            theta,
        )

    gimbal = ET.SubElement(robot, "link", name="left_stick_x_frame")
    _inertial(
        gimbal,
        mass["gimbal_link_mass_kg"],
        (0.0, 0.0, 0.0),
        tuple(mass["gimbal_inertia_kg_m2"]),
    )
    stick = ET.SubElement(robot, "link", name="left_stick")
    _inertial(
        stick,
        mass["stick_link_mass_kg"],
        tuple(mass["stick_com_m_from_pivot"]),
        tuple(mass["stick_inertia_kg_m2"]),
    )
    for key in ("lower_stem", "upper_stem", "cap"):
        item = collision[key]
        _cylinder_collision(
            stick,
            key,
            float(item["center_z_m"]),
            float(item["radius_m"]),
            float(item["length_m"]),
        )

    common_joint = dict(
        limit=float(k["half_sweep_rad"]),
        effort=float(dynamics["drive_force_limit_nm"]),
        velocity=float(dynamics["velocity_limit_rad_s"]),
        damping=float(dynamics["damping_nms_per_rad"]),
        friction=float(dynamics["joint_friction_nm"]),
    )
    _joint(
        robot,
        "left_stick_x",
        "controller_body",
        "left_stick_x_frame",
        pivot,
        tuple(k["horizontal_axis_source_frame"]),
        **common_joint,
    )
    _joint(
        robot,
        "left_stick_y",
        "left_stick_x_frame",
        "left_stick",
        (0.0, 0.0, 0.0),
        tuple(k["vertical_axis_source_frame"]),
        **common_joint,
    )
    ET.indent(robot, space="  ")
    ET.ElementTree(robot).write(
        output / "mobility.urdf", encoding="utf-8", xml_declaration=True
    )

    model_data = {
        "scale": 1.0,
        "transform_matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        "init_qpos": [0.0, 0.0],
        "target_points": [],
        "contact_points": [
            {
                "matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0.018], [0, 0, 0, 1]],
                "base": "left_stick",
            }
        ],
        "functional_points": [],
        "orientation_point": [],
        "contact_points_group": [],
        "contact_points_mask": [],
        "target_points_discription": [],
        "contact_points_discription": ["top center of the left-stick contact cap"],
        "functional_points_discription": [],
        "orientation_point_discription": [],
    }
    (output / "model_data.json").write_text(json.dumps(model_data, indent=2) + "\n", encoding="utf-8")

    scale = float(visual["meters_per_native_unit"])
    body_part = next(part for part in visual["parts"] if part["name"].startswith("05_Controller_Body"))
    # The common visual manifest intentionally stores topology but not bounds;
    # these are the reviewed whole-assembly extents from the metric registration.
    bounds = {
        "min": [-0.07664, -0.05554, -0.02986],
        "max": [0.07636, 0.04905, 0.03004],
        "unit": "m",
        "source": "metric-scaled approved visual assembly",
        "visual_body_part": body_part["name"],
        "meters_per_native_unit": scale,
    }
    (output / "bounding_box.json").write_text(json.dumps(bounds, indent=2) + "\n", encoding="utf-8")
    (output / "semantics.txt").write_text(
        "controller_body fixed controller_body\n"
        "left_stick_x_frame hinge left_stick_gimbal\n"
        "left_stick hinge left_stick\n",
        encoding="utf-8",
    )

    collision_manifest = {
        "schema_version": 1,
        "status": source["status"],
        "representation": "URDF primitives",
        "geometry": collision,
        "mass_properties": mass,
        "passive_dynamics": dynamics,
        "contact_material": contact,
        "source_record": "references/left_stick.json",
    }
    (output / "collision" / "manifest.json").write_text(
        json.dumps(collision_manifest, indent=2) + "\n", encoding="utf-8"
    )
    visual_binding = {
        "schema_version": 1,
        "source": "common/xbox_one_s/visual/manifest.json",
        "root_link": "controller_body",
        "moving_parts": {
            "09_Stick_L_VISUAL_UNCALIBRATED": {
                "link": "left_stick",
                "pivot_m_source_frame": list(pivot),
            }
        },
        "static_parts": [
            part["name"]
            for part in visual["parts"]
            if part["name"] != "09_Stick_L_VISUAL_UNCALIBRATED"
        ],
    }
    (output / "visual" / "manifest.json").write_text(
        json.dumps(visual_binding, indent=2) + "\n", encoding="utf-8"
    )

    required = [
        "mobility.urdf",
        "model_data.json",
        "bounding_box.json",
        "semantics.txt",
        "visual/manifest.json",
        "collision/manifest.json",
    ]
    manifest = {
        "schema_version": 1,
        "asset_id": "xbox_one_s",
        "backend": "robotwin",
        "profile": source["profile"],
        "available": True,
        "dynamics_ready": True,
        "entrypoint": "mobility.urdf",
        "required_files": required,
        "reason": None,
        "scope": source["scope"],
        "evidence_status": source["status"],
        "parameter_status": source["parameter_status"],
        "hardware_calibrated": source["hardware_calibrated"],
        "source_record": "references/left_stick.json",
        "joint_dynamics": [
            {
                "name": name,
                "stiffness": dynamics["linear_equivalent_stiffness_nm_per_rad"],
                "damping": dynamics["damping_nms_per_rad"],
                "force_limit": dynamics["drive_force_limit_nm"],
                "friction": dynamics["joint_friction_nm"],
                "target": 0.0,
            }
            for name in ("left_stick_x", "left_stick_y")
        ],
        "state_mapping": {
            "axes": [
                {
                    "channel": "left_x",
                    "joint": "left_stick_x",
                    "lower": -k["half_sweep_rad"],
                    "upper": k["half_sweep_rad"],
                },
                {
                    "channel": "left_y",
                    "joint": "left_stick_y",
                    "lower": -k["half_sweep_rad"],
                    "upper": k["half_sweep_rad"],
                },
            ],
            "radial_groups": [{"channels": ["left_x", "left_y"], "radius": 1.0}],
            "deadzone": None,
        },
        "contact_material": contact,
        "visual_binding": visual_binding,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"output": str(output), "profile": source["profile"], "joints": 2, "gate_segments": count}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.output.resolve())


if __name__ == "__main__":
    main()
