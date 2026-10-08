"""Build the first-pass full Xbox One S RoboTwin/SAPIEN articulation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import trimesh


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources" / "full_controls_estimated_v0.json"
PROFILE = ROOT / "assets" / "appearance_matched_estimated_v0" / "viewer_profile.json"
VISUAL_ROOT = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "common"
    / "xbox_one_s"
    / "visual"
)
LEFT_STICK_SOURCE = ROOT / "sources" / "robotwin_left_stick_estimated_v0.json"
DEFAULT_OUTPUT = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "robotwin"
    / "full_controls_estimated_v0"
)

PART_BY_CONTROL = {
    "a": "00_A_Button_VISUAL_UNCALIBRATED",
    "b": "01_B_Button_VISUAL_UNCALIBRATED",
    "left_shoulder": "02_Bumper_L_VISUAL_UNCALIBRATED",
    "right_shoulder": "03_Bumper_R_VISUAL_UNCALIBRATED",
    "pair": "04_Connect_Button_VISUAL_UNCALIBRATED",
    "shell": "05_Controller_Body_VISUAL_UNCALIBRATED",
    "dpad": "06_D-Pad_VISUAL_UNCALIBRATED",
    "view": "07_Menu_L_VISUAL_UNCALIBRATED",
    "menu": "08_Menu_R_VISUAL_UNCALIBRATED",
    "left_stick": "09_Stick_L_VISUAL_UNCALIBRATED",
    "right_stick": "10_Stick_R_VISUAL_UNCALIBRATED",
    "left_trigger": "11_Trigger_L_VISUAL_UNCALIBRATED",
    "right_trigger": "12_Trigger_R_VISUAL_UNCALIBRATED",
    "x": "13_X_Button_VISUAL_UNCALIBRATED",
    "guide": "14_XboxButton_VISUAL_UNCALIBRATED",
    "y": "15_Y_Button_VISUAL_UNCALIBRATED",
}

W3C_TO_CANONICAL = {
    0: "left_x", 1: "left_y", 2: "right_x", 3: "right_y",
    4: "south", 5: "east", 6: "west", 7: "north",
    8: "left_shoulder", 9: "right_shoulder",
    10: "left_trigger", 11: "right_trigger",
    12: "back", 13: "start", 14: "left_stick", 15: "right_stick",
    16: "dpad_up", 17: "dpad_down", 18: "dpad_left", 19: "dpad_right",
    20: "guide",
}


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fmt(value: float) -> str:
    return f"{float(value):.12g}"


def _vec(values) -> str:
    return " ".join(_fmt(value) for value in values)


def _origin(parent: ET.Element, xyz, rpy=(0.0, 0.0, 0.0)) -> None:
    ET.SubElement(parent, "origin", xyz=_vec(xyz), rpy=_vec(rpy))


def _inertial(link: ET.Element, mass: float, com, inertia) -> None:
    node = ET.SubElement(link, "inertial")
    _origin(node, com)
    ET.SubElement(node, "mass", value=_fmt(mass))
    ET.SubElement(
        node,
        "inertia",
        ixx=_fmt(inertia[0]),
        ixy="0",
        ixz="0",
        iyy=_fmt(inertia[1]),
        iyz="0",
        izz=_fmt(inertia[2]),
    )


def _box_inertia(mass: float, size) -> tuple[float, float, float]:
    x, y, z = (float(value) for value in size)
    return (
        mass * (y * y + z * z) / 12.0,
        mass * (x * x + z * z) / 12.0,
        mass * (x * x + y * y) / 12.0,
    )


def _add_box(link: ET.Element, name: str, center, size, yaw=0.0) -> dict:
    collision = ET.SubElement(link, "collision", name=name)
    _origin(collision, center, (0.0, 0.0, yaw))
    geometry = ET.SubElement(collision, "geometry")
    ET.SubElement(geometry, "box", size=_vec(size))
    return {"type": "box", "center": list(center), "size": list(size), "yaw": yaw}


def _add_cylinder(link: ET.Element, name: str, center, radius, length) -> dict:
    collision = ET.SubElement(link, "collision", name=name)
    _origin(collision, center)
    geometry = ET.SubElement(collision, "geometry")
    ET.SubElement(geometry, "cylinder", radius=_fmt(radius), length=_fmt(length))
    return {
        "type": "cylinder",
        "center": list(center),
        "radius": radius,
        "length": length,
    }


def _joint_element(robot: ET.Element, record: dict, parent: str, child: str, origin) -> None:
    joint = ET.SubElement(robot, "joint", name=record["id"], type=record["type"])
    _origin(joint, origin)
    ET.SubElement(joint, "parent", link=parent)
    ET.SubElement(joint, "child", link=child)
    ET.SubElement(joint, "axis", xyz=_vec(record["axis_source"]))
    ET.SubElement(
        joint,
        "limit",
        lower=_fmt(record["limits"][0]),
        upper=_fmt(record["limits"][1]),
        effort=_fmt(record["effort"]),
        velocity=_fmt(record["velocity"]),
    )
    ET.SubElement(
        joint,
        "dynamics",
        damping=_fmt(record["passive_damping"]),
        friction=_fmt(record["friction"]),
    )


def _converted_bounds(part_file: Path, scale: float) -> np.ndarray:
    loaded = trimesh.load(part_file, force="scene", process=False)
    mesh = loaded.dump(concatenate=True)
    vertices = np.asarray(mesh.vertices, dtype=np.float64) * scale
    converted = np.column_stack((vertices[:, 0], -vertices[:, 2], vertices[:, 1]))
    return np.stack((converted.min(axis=0), converted.max(axis=0)))


def _critical_damping(stiffness: float, effective_mass: float, ratio: float) -> float:
    return 2.0 * ratio * math.sqrt(stiffness * effective_mass)


def build(output: Path) -> None:
    source = _json(SOURCE)
    profile = _json(PROFILE)
    visual = _json(VISUAL_ROOT / "manifest.json")
    left_stick = _json(LEFT_STICK_SOURCE)
    output.mkdir(parents=True, exist_ok=True)
    (output / "collision").mkdir(exist_ok=True)
    (output / "visual").mkdir(exist_ok=True)

    joints = {joint["id"]: dict(joint) for joint in profile["joints"]}
    nodes = {node["control"]: node for node in profile["nodes"]}
    scale = float(visual["meters_per_native_unit"])
    bounds = {
        control: _converted_bounds(VISUAL_ROOT / next(
            part["file"] for part in visual["parts"] if part["name"] == part_name
        ), scale)
        for control, part_name in PART_BY_CONTROL.items()
    }

    face = set(source["control_groups"]["face_buttons"]["joints"])
    small = set(source["control_groups"]["small_buttons"]["joints"])
    shoulders = set(source["control_groups"]["shoulders"]["joints"])
    triggers = set(source["control_groups"]["triggers"]["joints"])
    dpad = set(source["control_groups"]["dpad"]["joints"])
    stick_tilts = {
        "left_stick_x", "left_stick_y", "right_stick_x", "right_stick_y"
    }
    stick_clicks = {"left_stick_click", "right_stick_click"}
    one_sided = face | small | shoulders | triggers | stick_clicks
    preload_fraction = float(
        source["passive_preload_policy"]["preload_fraction"]
    )

    dynamics = {}
    for name, joint in joints.items():
        travel = float(joint["limits"][1] - joint["limits"][0])
        if name in face:
            force = float(source["control_groups"]["face_buttons"]["reference_force_n"])
            stiffness, effort, velocity, effective = force / travel, 2 * force, 1.0, 0.001
        elif name in small:
            force = float(source["control_groups"]["small_buttons"]["reference_force_n"])
            stiffness, effort, velocity, effective = force / travel, 2 * force, 1.0, 0.0005
        elif name in shoulders:
            force = float(source["control_groups"]["shoulders"]["reference_force_n"])
            stiffness, effort, velocity, effective = force / travel, 2 * force, 1.0, 0.003
        elif name in triggers:
            torque = float(source["control_groups"]["triggers"]["endpoint_torque_nm"])
            stiffness, effort, velocity, effective = torque / travel, 0.024, 10.0, 1e-6
        elif name in stick_tilts:
            record = left_stick["passive_dynamics"]
            stiffness = float(record["linear_equivalent_stiffness_nm_per_rad"])
            effort = float(record["drive_force_limit_nm"])
            velocity = float(record["velocity_limit_rad_s"])
            effective = 0.8e-6
        elif name in stick_clicks:
            group = source["control_groups"]["sticks"]
            stiffness = float(group["click_stiffness_n_per_m"])
            effort = float(group["click_force_limit_n"])
            velocity, effective = 0.2, 0.004
        elif name in dpad:
            group = source["control_groups"]["dpad"]
            stiffness = float(group["stiffness_nm_per_rad"])
            effort = float(group["force_limit_nm"])
            velocity, effective = 10.0, 1e-6
        else:
            raise ValueError(f"joint {name!r} has no dynamics policy")
        ratio = 0.7
        damping = _critical_damping(stiffness, effective, ratio)
        joint.update(
            effort=effort,
            velocity=velocity,
            stiffness=stiffness,
            drive_damping=damping,
            passive_damping=damping * 0.05,
            friction=0.0,
            target=(-preload_fraction * travel if name in one_sided else 0.0),
        )
        dynamics[name] = joint

    robot = ET.Element("robot", name="xbox_one_s_full_controls_estimated_v0")
    link_elements = {"controller_body": ET.SubElement(robot, "link", name="controller_body")}
    primitive_records = {"controller_body": []}
    body_mass = float(source["mass_policy"]["whole_controller_mass_kg"])

    # Create the link graph before assigning masses and collisions.
    link_graph = {}
    final_link_by_control = {}
    for control, node in nodes.items():
        if control == "shell":
            continue
        joint_ids = node["joint_ids"]
        parent = "controller_body"
        for index, joint_id in enumerate(joint_ids):
            child = control if index == len(joint_ids) - 1 else f"{joint_id}_frame"
            if child not in link_elements:
                link_elements[child] = ET.SubElement(robot, "link", name=child)
                primitive_records[child] = []
            origin = dynamics[joint_id]["pivot_source_m"] if index == 0 else [0, 0, 0]
            link_graph[joint_id] = (parent, child, origin)
            parent = child
        final_link_by_control[control] = parent

    # Collision primitives and estimated mass properties.
    moving_mass = {}
    density = float(source["mass_policy"]["polymer_density_kg_m3"])
    fit = float(source["collision_policy"]["fit_scale"])
    fill = source["mass_policy"]["solid_fill_factors"]
    minimum_mass = float(source["mass_policy"]["minimum_moving_mass_kg"])

    for control, link_name in final_link_by_control.items():
        link = link_elements[link_name]
        pivot = np.asarray(dynamics[nodes[control]["joint_ids"][0]]["pivot_source_m"])
        box = bounds[control]
        center = (box.mean(axis=0) - pivot).tolist()
        extents = (box[1] - box[0]) * fit
        records = primitive_records[link_name]
        if control in {"a", "b", "x", "y", "view", "menu", "guide"}:
            radius = float(min(extents[0], extents[1]) * 0.45)
            length = float(extents[2])
            records.append(_add_cylinder(link, f"{control}_cap", center, radius, length))
            volume = math.pi * radius * radius * length
            factor = float(fill["buttons"])
        elif control in {"left_stick", "right_stick"}:
            proxy = left_stick["collision_geometry"]
            for key in ("lower_stem", "upper_stem", "cap"):
                item = proxy[key]
                records.append(_add_cylinder(
                    link,
                    f"{control}_{key}",
                    [0, 0, float(item["center_z_m"])],
                    float(item["radius_m"]),
                    float(item["length_m"]),
                ))
            volume = sum(
                math.pi * float(proxy[key]["radius_m"]) ** 2 * float(proxy[key]["length_m"])
                for key in ("lower_stem", "upper_stem", "cap")
            )
            factor = 1.0
        elif control == "dpad":
            arm = float(max(extents[0], extents[1]))
            width = float(min(extents[0], extents[1]) * 0.34)
            height = float(extents[2])
            records.append(_add_box(link, "dpad_horizontal", center, [arm, width, height]))
            records.append(_add_box(link, "dpad_vertical", center, [width, arm, height]))
            volume = 2 * arm * width * height - width * width * height
            factor = float(fill["dpad"])
        else:
            size = (extents * np.array([1.0, 1.0, 0.9])).tolist()
            records.append(_add_box(link, f"{control}_box", center, size))
            volume = float(np.prod(size))
            factor = float(fill["triggers"] if "trigger" in control else fill["bumpers"])
        moving_mass[link_name] = max(minimum_mass, density * volume * factor)

    # Intermediate frames have explicit small inertias.
    for link_name in link_elements:
        if link_name == "controller_body" or link_name in moving_mass:
            continue
        moving_mass[link_name] = 0.0005
    body_mass -= sum(moving_mass.values())
    if body_mass <= 0:
        raise ValueError("moving mass estimates exceed whole controller mass")

    floor = float(source["mass_policy"]["minimum_diagonal_inertia_kg_m2"])
    for link_name, link in link_elements.items():
        if link_name == "controller_body":
            continue
        mass = moving_mass[link_name]
        records = primitive_records[link_name]
        if records:
            centers = np.asarray([record["center"] for record in records])
            com = centers.mean(axis=0)
            if records[0]["type"] == "box":
                inertia = _box_inertia(mass, records[0]["size"])
            else:
                radius = float(records[0]["radius"])
                length = float(records[0]["length"])
                inertia = (
                    mass * (3 * radius * radius + length * length) / 12,
                    mass * (3 * radius * radius + length * length) / 12,
                    mass * radius * radius / 2,
                )
        else:
            com = np.zeros(3)
            inertia = (2e-8, 2e-8, 2e-8)
        _inertial(link, mass, com, [max(floor, value) for value in inertia])

    _inertial(
        link_elements["controller_body"],
        body_mass,
        [-0.00014, -0.00325, -0.00475],
        left_stick["mass_properties"]["body_inertia_kg_m2"],
    )
    primitive_records["controller_body"].append(
        _add_box(
            link_elements["controller_body"],
            "body_central_support",
            [0, 0, -0.018],
            [0.12, 0.075, 0.028],
        )
    )
    gate = left_stick["collision_geometry"]["gate"]
    for control in ("left_stick", "right_stick"):
        pivot = np.asarray(dynamics[f"{control}_x"]["pivot_source_m"])
        count = int(gate["segments"])
        inner = float(gate["inner_radius_m"])
        outer = float(gate["outer_radius_m"])
        for index in range(count):
            angle = 2 * math.pi * index / count
            center = [
                pivot[0] + 0.5 * (inner + outer) * math.cos(angle),
                pivot[1] + 0.5 * (inner + outer) * math.sin(angle),
                pivot[2] + float(gate["center_z_m"]),
            ]
            size = [
                outer - inner,
                2 * inner * math.tan(math.pi / count),
                float(gate["height_m"]),
            ]
            primitive_records["controller_body"].append(
                _add_box(
                    link_elements["controller_body"],
                    f"{control}_gate_{index:02d}",
                    center,
                    size,
                    angle,
                )
            )

    for joint_id, (parent, child, origin) in link_graph.items():
        _joint_element(robot, dynamics[joint_id], parent, child, origin)

    ET.indent(robot, space="  ")
    ET.ElementTree(robot).write(
        output / "mobility.urdf", encoding="utf-8", xml_declaration=True
    )

    axis_mappings = []
    scalar_mappings = []
    split_mappings = []
    physical_events = []
    for joint_id, joint in dynamics.items():
        driver = joint["driver"]
        if driver["kind"] == "linear_channel":
            channel = W3C_TO_CANONICAL[int(driver["channel"])]
            item = {
                "channel": channel,
                "joint": joint_id,
                "lower": joint["limits"][0],
                "upper": joint["limits"][1],
            }
            (axis_mappings if channel in {"left_x", "left_y", "right_x", "right_y"}
             else scalar_mappings).append(item)
        elif driver["kind"] == "difference_channels":
            split_mappings.append({
                "negative_channel": W3C_TO_CANONICAL[int(driver["negative_channel"])],
                "positive_channel": W3C_TO_CANONICAL[int(driver["positive_channel"])],
                "joint": joint_id,
                "lower": joint["limits"][0],
                "upper": joint["limits"][1],
            })
        elif driver["kind"] == "physical_event":
            physical_events.append({
                "event": driver["event"],
                "joint": joint_id,
                "lower": joint["limits"][0],
                "upper": joint["limits"][1],
            })

    visual_binding = {
        "schema_version": 1,
        "source": "common/xbox_one_s/visual/manifest.json",
        "source_sha256": _sha256(VISUAL_ROOT / "manifest.json"),
        "root_link": "controller_body",
        "moving_parts": {
            PART_BY_CONTROL[control]: {
                "link": link,
                "pivot_m_source_frame": dynamics[nodes[control]["joint_ids"][0]]["pivot_source_m"],
            }
            for control, link in final_link_by_control.items()
        },
        "static_parts": [PART_BY_CONTROL["shell"]],
    }
    collision_manifest = {
        "schema_version": 1,
        "method": source["collision_policy"],
        "links": primitive_records,
        "mass_kg": {"controller_body": body_mass, **moving_mass},
        "source": "sources/full_controls_estimated_v0.json",
    }
    (output / "visual" / "manifest.json").write_text(
        json.dumps(visual_binding, indent=2) + "\n", encoding="utf-8"
    )
    (output / "collision" / "manifest.json").write_text(
        json.dumps(collision_manifest, indent=2) + "\n", encoding="utf-8"
    )
    (output / "model_data.json").write_text(
        json.dumps({
            "scale": 1.0,
            "transform_matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "init_qpos": [0.0] * len(dynamics),
            "target_points": [],
            "contact_points": [],
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    body_bounds = bounds["shell"]
    (output / "bounding_box.json").write_text(
        json.dumps({"min": body_bounds[0].tolist(), "max": body_bounds[1].tolist()}, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "semantics.txt").write_text(
        "\n".join(f"{child} {joint_id} {joint_id}" for joint_id, (_, child, _) in link_graph.items()) + "\n",
        encoding="utf-8",
    )

    required = [
        "mobility.urdf", "model_data.json", "bounding_box.json", "semantics.txt",
        "visual/manifest.json", "collision/manifest.json",
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
        "source_record": "sources/full_controls_estimated_v0.json",
        "source_sha256": _sha256(SOURCE),
        "joint_dynamics": [
            {
                "name": name,
                "stiffness": joint["stiffness"],
                "damping": joint["drive_damping"],
                "force_limit": joint["effort"],
                "friction": joint["friction"],
                "target": joint["target"],
            }
            for name, joint in dynamics.items()
        ],
        "state_mapping": {
            "axes": axis_mappings,
            "scalars": scalar_mappings,
            "splits": split_mappings,
            "radial_groups": [
                {"channels": ["left_x", "left_y"], "radius": 1.0},
                {"channels": ["right_x", "right_y"], "radius": 1.0},
            ],
            "radial_source_groups": [
                {"joints": ["dpad_horizontal", "dpad_vertical"], "radius": 1.0}
            ],
            "physical_events": physical_events,
            "deadzone": None,
        },
        "contact_material": left_stick["contact_material"],
        "visual_binding": visual_binding,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": str(output),
        "joints": len(dynamics),
        "game_channels": len(axis_mappings) + len(scalar_mappings) + 2 * len(split_mappings),
        "physical_events": len(physical_events),
        "body_mass_kg": body_mass,
    }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.output.resolve())


if __name__ == "__main__":
    main()
