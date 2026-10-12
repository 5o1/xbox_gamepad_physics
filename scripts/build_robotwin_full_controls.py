"""Build the first-pass full Xbox One S RoboTwin/SAPIEN articulation."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import trimesh

from build_kinematics import build as build_kinematics
from build_common_collision import MESHBASE, shell_meshes


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "references" / "full_controls.json"
VISUAL_ROOT = (
    ROOT
    / "build"
    / "resources"
    / "common"
    / "xbox_one_s"
    / "visual"
)
LEFT_STICK_SOURCE = ROOT / "references" / "left_stick.json"
COMMON_MOTION = (
    ROOT
    / "build"
    / "resources"
    / "common"
    / "xbox_one_s"
    / "motion"
    / "full_controls.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "build"
    / "standalone"
    / "robotwin"
    / "full_controls"
)
COLLISION_ROOT = ROOT / "build/resources/common/xbox_one_s/collision"

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

def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _fmt(value: float) -> str:
    return f"{float(value):.17g}"


def _vec(values) -> str:
    return " ".join(_fmt(value) for value in values)


def _origin(parent: ET.Element, xyz, rpy=(0.0, 0.0, 0.0)) -> None:
    ET.SubElement(parent, "origin", xyz=_vec(xyz), rpy=_vec(rpy))


def _inertial(link: ET.Element, mass: float, com, inertia) -> None:
    tensor = np.asarray(inertia, dtype=float)
    if tensor.shape == (3,):
        tensor = np.diag(tensor)
    if not np.allclose(tensor, tensor.T, atol=1e-18) or np.linalg.eigvalsh(tensor).min() <= 0:
        raise ValueError(f"{link.get('name')}: inertia tensor must be positive definite")
    node = ET.SubElement(link, "inertial")
    _origin(node, com)
    ET.SubElement(node, "mass", value=_fmt(mass))
    ET.SubElement(
        node,
        "inertia",
        ixx=_fmt(tensor[0, 0]),
        ixy=_fmt(tensor[0, 1]),
        ixz=_fmt(tensor[0, 2]),
        iyy=_fmt(tensor[1, 1]),
        iyz=_fmt(tensor[1, 2]),
        izz=_fmt(tensor[2, 2]),
    )


def _joint_element(robot: ET.Element, record: dict, parent: str, child: str, origin, rpy=(0, 0, 0)) -> None:
    joint = ET.SubElement(robot, "joint", name=record["id"], type=record["type"])
    _origin(joint, origin, rpy)
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


def _link_transforms(motion):
    transforms = {"controller_body": np.eye(4)}
    pending = list(motion["joints"])
    while pending:
        ready = [joint for joint in pending if joint["parent"] in transforms]
        if not ready:
            raise ValueError("motion joint chain is disconnected")
        for joint in ready:
            transform = trimesh.transformations.euler_matrix(*joint.get("rpy", (0, 0, 0)), axes="sxyz")
            transform[:3, 3] = joint["origin"]
            transforms[joint["child"]] = transforms[joint["parent"]] @ transform
            pending.remove(joint)
    return transforms


def _transform_obj(source, destination, transform):
    lines = []
    for line in source.read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == "v":
            vertex = transform @ np.array([*(float(x) for x in fields[1:4]), 1.0])
            line = "v " + _vec(vertex[:3])
        lines.append(line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n")


def _mass_mesh(component, transform):
    shells = shell_meshes(MESHBASE / "meshes" / f"{component}.obj")
    if len(shells) == 2:
        import manifold3d
        solids = [manifold3d.Manifold(manifold3d.Mesh64(
            np.asarray(mesh.vertices), np.asarray(mesh.faces, dtype=np.uint64))) for mesh in shells]
        union = solids[0] + solids[1]
        if union.status() != manifold3d.Error.NoError:
            raise ValueError(f"{component}: manifold union failed: {union.status()}")
        result = union.to_mesh64()
        mesh = trimesh.Trimesh(result.vert_properties[:, :3], result.tri_verts, process=False)
    else:
        mesh = shells[0]
    mesh.apply_transform(transform)
    return mesh


def build(output: Path, *, kinematics: Path | None = None,
          visual_root: Path = VISUAL_ROOT, common_motion: Path = COMMON_MOTION,
          collision_root: Path = COLLISION_ROOT) -> None:
    source = _json(SOURCE)
    profile = _json(kinematics) if kinematics is not None else build_kinematics()[1]
    motion = _json(common_motion)
    visual = _json(visual_root / "manifest.json")
    left_stick = _json(LEFT_STICK_SOURCE)
    output.mkdir(parents=True, exist_ok=True)
    (output / "collision").mkdir(exist_ok=True)
    (output / "visual").mkdir(exist_ok=True)

    motion_joints = {joint["name"]: joint for joint in motion["joints"]}
    joints = {joint["id"]: dict(joint) for joint in profile["joints"]}
    if set(joints) != set(motion_joints):
        raise ValueError("common motion contract and kinematic profile joint names differ")
    for name, joint in joints.items():
        common = motion_joints[name]
        joint["type"] = common["type"]
        joint["axis_source"] = common["axis"]
        joint["limits"] = [common["lower"], common["upper"]]
        joint["unit"] = common["unit"]
    nodes = {node["control"]: node for node in profile["nodes"]}
    scale = float(visual["meters_per_native_unit"])
    bounds = {
        control: _converted_bounds(visual_root / next(
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
            friction=(
                float(source["control_groups"]["sticks"]["tilt_joint_friction_coefficient"])
                if name in stick_tilts
                else 0.0
            ),
            target=(-preload_fraction * travel if name in one_sided else 0.0),
        )
        dynamics[name] = joint

    robot = ET.Element("robot", name="xbox_one_s_full_controls")
    link_elements = {"controller_body": ET.SubElement(robot, "link", name="controller_body")}
    collision_records = {"controller_body": {"coacd": [], "sdf": [], "hull_count": 0}}
    body_mass = float(source["mass_policy"]["whole_controller_mass_kg"])

    # The public motion contract owns the articulation topology.
    link_graph = {}
    for joint in motion["joints"]:
        child = joint["child"]
        if child not in link_elements:
            link_elements[child] = ET.SubElement(robot, "link", name=child)
            collision_records[child] = {"coacd": [], "sdf": [], "hull_count": 0}
        link_graph[joint["name"]] = (
            joint["parent"],
            child,
            joint["origin"],
        )
    final_link_by_control = {
        control: motion_joints[node["joint_ids"][-1]]["child"]
        for control, node in nodes.items()
        if control != "shell"
    }

    # Neutral transforms come from the complete motion chain, including frames.
    transforms = _link_transforms(motion)
    common_collision = _json(collision_root / "manifest.json")
    moving_mass, mass_properties = {}, {}
    density = float(source["mass_policy"]["polymer_density_kg_m3"])
    fill = source["mass_policy"]["solid_fill_factors"]
    minimum_mass = float(source["mass_policy"]["minimum_moving_mass_kg"])
    for component, record in common_collision["components"].items():
        link_name = "controller_body" if component in {"shell", "shell_front_plate"} else final_link_by_control[component]
        if link_name != "controller_body":
            pivot = np.asarray(dynamics[nodes[component]["joint_ids"][0]]["pivot_source_m"])
            assert np.max(np.abs(transforms[link_name][:3, 3] - pivot)) <= 1e-12, component
        local = np.linalg.inv(transforms[link_name])
        target = collision_records[link_name]
        for variant in ("coacd", "sdf"):
            for relative in record[variant]:
                filename = "collision/" + relative
                _transform_obj(collision_root / relative, output / filename, local)
                target[variant].append(filename)
        target["hull_count"] += record["hull_count"]
        collision = ET.SubElement(link_elements[link_name], "collision", name=component)
        geometry = ET.SubElement(collision, "geometry")
        ET.SubElement(geometry, "mesh", filename="collision/" + record["coacd"][0])
        if link_name == "controller_body":
            continue
        mesh = _mass_mesh(component, local)
        properties = mesh.mass_properties
        if properties.volume <= 0:
            raise ValueError(f"{component}: meshbase volume must be positive")
        group = ("sticks" if "stick" in component else "triggers" if "trigger" in component
                 else "bumpers" if "shoulder" in component else "dpad" if component == "dpad" else "buttons")
        raw_mass = properties.volume * density * float(fill[group])
        mass = max(minimum_mass, raw_mass)
        # Unit-density centroidal tensor, scaled to the final clamped mass.
        tensor = np.asarray(properties.inertia) * (mass / properties.mass)
        moving_mass[link_name] = mass
        mass_properties[link_name] = {"volume_m3": properties.volume, "unclamped_mass_kg": raw_mass,
            "mass_kg": mass, "com_m": properties.center_mass.tolist(), "inertia_kg_m2": tensor.tolist()}
        _inertial(link_elements[link_name], mass, properties.center_mass, tensor)

    for link_name, link in link_elements.items():
        if link_name == "controller_body" or link_name in moving_mass:
            continue
        moving_mass[link_name] = 0.0005
        _inertial(link, 0.0005, np.zeros(3), np.eye(3) * 2e-8)
    body_mass -= sum(moving_mass.values())
    if body_mass <= 0:
        raise ValueError("moving mass estimates exceed whole controller mass")
    assert abs(body_mass + sum(moving_mass.values()) - 0.28) <= 1e-12
    _inertial(link_elements["controller_body"], body_mass,
              [-0.00014, -0.00325, -0.00475], left_stick["mass_properties"]["body_inertia_kg_m2"])
    for link_name, record in collision_records.items():
        record["mass_kg"] = body_mass if link_name == "controller_body" else moving_mass[link_name]

    for joint_id, (parent, child, origin) in link_graph.items():
        _joint_element(robot, dynamics[joint_id], parent, child, origin, motion_joints[joint_id].get("rpy", (0, 0, 0)))

    ET.indent(robot, space="  ")
    ET.ElementTree(robot).write(
        output / "mobility.urdf", encoding="utf-8", xml_declaration=True
    )

    visual_binding = {
        "schema_version": 1,
        "source": "common/xbox_one_s/visual/manifest.json",
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
        "links": collision_records,
        "moving_mass_properties": mass_properties,
        "mass_kg": {"controller_body": body_mass, **moving_mass},
        "source": "references/full_controls.json",
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
    required.extend(relative for record in collision_records.values() for variant in ("coacd", "sdf") for relative in record[variant])
    manifest = {
        "default_collision": "sdf",
        "min_sapien": "3.0.3",
        "collision_variants": {
            "coacd": {"source": "urdf"},
            "sdf": {"min_sapien": "3.0.3", "spacing_m": source["collision_policy"]["sdf"]["spacing_m"],
                    "links": {name: record["sdf"] for name, record in collision_records.items()}},
        },
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
        "source_record": "references/full_controls.json",
        "motion_contract": "common/xbox_one_s/motion/full_controls.json",
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
        "contact_material": left_stick["contact_material"],
        "visual_binding": visual_binding,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": str(output),
        "joints": len(dynamics),
        "game_channels": len(motion["bindings"]["axes"]) + len(motion["bindings"]["scalars"]) + 2 * len(motion["bindings"]["splits"]),
        "physical_events": len(motion["bindings"]["physical_events"]),
        "body_mass_kg": body_mass,
    }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.output.resolve())


if __name__ == "__main__":
    main()
