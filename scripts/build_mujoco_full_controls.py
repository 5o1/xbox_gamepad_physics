"""Generate MuJoCo MJCF from the shared full-controls RoboTwin mechanism."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ROBOTWIN = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "robotwin"
    / "full_controls"
)
VISUAL = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "mujoco"
    / "visual_v0"
)
SOURCE = ROOT / "references" / "full_controls.json"
DEFAULT_OUTPUT = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "mujoco"
    / "full_controls"
)
STICK_TILT_JOINTS = {
    "left_stick_x",
    "left_stick_y",
    "right_stick_x",
    "right_stick_y",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt(value: float) -> str:
    return f"{float(value):.12g}"


def _vec(values) -> str:
    return " ".join(_fmt(value) for value in values)


def _urdf_records() -> tuple[dict, dict, dict]:
    root = ET.parse(ROBOTWIN / "mobility.urdf").getroot()
    links = {}
    for link in root.findall("link"):
        inertial = link.find("inertial")
        inertia = inertial.find("inertia")
        links[link.get("name")] = {
            "mass": float(inertial.find("mass").get("value")),
            "com": [float(value) for value in inertial.find("origin").get("xyz").split()],
            "inertia": [
                float(inertia.get("ixx")),
                float(inertia.get("iyy")),
                float(inertia.get("izz")),
            ],
        }
    joints = {}
    children = {}
    for joint in root.findall("joint"):
        record = {
            "name": joint.get("name"),
            "type": joint.get("type"),
            "parent": joint.find("parent").get("link"),
            "child": joint.find("child").get("link"),
            "pos": [float(value) for value in joint.find("origin").get("xyz").split()],
            "axis": [float(value) for value in joint.find("axis").get("xyz").split()],
            "range": [
                float(joint.find("limit").get("lower")),
                float(joint.find("limit").get("upper")),
            ],
        }
        joints[record["name"]] = record
        children.setdefault(record["parent"], []).append(record)
    return links, joints, children


def _base_document(model: str) -> tuple[ET.Element, ET.Element, ET.Element]:
    root = ET.Element("mujoco", model=model)
    ET.SubElement(
        root,
        "compiler",
        angle="radian",
        autolimits="true",
        discardvisual="false",
    )
    ET.SubElement(
        root,
        "option",
        timestep=_fmt(1 / 240),
        gravity="0 0 -9.81",
        integrator="discrete",
    )
    default = ET.SubElement(root, "default")
    ET.SubElement(
        default,
        "geom",
        contype="1",
        conaffinity="1",
        friction="0.4 0.005 0.0001",
        solref="0.01 1",
        solimp="0.9 0.95 0.001",
    )
    asset = ET.SubElement(root, "asset")
    worldbody = ET.SubElement(root, "worldbody")
    return root, asset, worldbody


def build(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    robotwin_manifest = _json(ROBOTWIN / "manifest.json")
    source = _json(SOURCE)
    collision = _json(ROBOTWIN / "collision" / "manifest.json")
    visual_binding = _json(ROBOTWIN / "visual" / "manifest.json")
    visual_manifest = _json(VISUAL / "visual_manifest.json")
    links, joints, children = _urdf_records()
    dynamics = {item["name"]: item for item in robotwin_manifest["joint_dynamics"]}

    root, asset, worldbody = _base_document("xbox_one_s_full_controls")
    ET.SubElement(
        asset,
        "texture",
        name="xbox_base_color",
        type="2d",
        file="../visual_v0/textures/base_color.png",
        colorspace="sRGB",
        vflip="true",
    )
    ET.SubElement(
        asset,
        "material",
        name="xbox_surface",
        texture="xbox_base_color",
        rgba="1 1 1 1",
        specular=".5",
        shininess=".2",
    )
    part_files = {part["name"]: part["file"] for part in visual_manifest["parts"]}
    scale = visual_manifest["scale"]
    for part_name, filename in part_files.items():
        ET.SubElement(
            asset,
            "mesh",
            name=part_name,
            file=f"../visual_v0/meshes/{filename}",
            scale=f"{scale} {scale} {scale}",
            smoothnormal="false",
        )

    visual_by_link = {"controller_body": []}
    visual_by_link["controller_body"].extend(visual_binding["static_parts"])
    pivot_by_part = {}
    for part_name, binding in visual_binding["moving_parts"].items():
        visual_by_link.setdefault(binding["link"], []).append(part_name)
        pivot_by_part[part_name] = binding["pivot_m_source_frame"]

    def add_geoms(body: ET.Element, link_name: str) -> None:
        for index, primitive in enumerate(collision["links"].get(link_name, [])):
            attributes = {
                "name": f"collision_{link_name}_{index:02d}",
                "type": primitive["type"],
                "pos": _vec(primitive["center"]),
                "rgba": ".2 .55 .8 .15",
                "group": "0",
                "density": "0",
            }
            if primitive["type"] == "box":
                attributes["size"] = _vec(float(value) / 2 for value in primitive["size"])
                if primitive.get("yaw"):
                    attributes["euler"] = f"0 0 {_fmt(primitive['yaw'])}"
            elif primitive["type"] == "cylinder":
                attributes["size"] = _vec(
                    [primitive["radius"], float(primitive["length"]) / 2]
                )
            else:
                raise ValueError(f"unsupported collision primitive {primitive['type']}")
            ET.SubElement(body, "geom", **attributes)

        for part_name in visual_by_link.get(link_name, []):
            pivot = pivot_by_part.get(part_name, [0, 0, 0])
            ET.SubElement(
                body,
                "geom",
                name=f"visual_{part_name}",
                type="mesh",
                mesh=part_name,
                material="xbox_surface",
                pos=_vec(-float(value) for value in pivot),
                quat=".707106781186548 .707106781186548 0 0",
                contype="0",
                conaffinity="0",
                group="1",
                density="0",
            )

    def add_body(parent_xml: ET.Element, link_name: str, pos) -> ET.Element:
        body = ET.SubElement(parent_xml, "body", name=link_name, pos=_vec(pos))
        link = links[link_name]
        ET.SubElement(
            body,
            "inertial",
            pos=_vec(link["com"]),
            mass=_fmt(link["mass"]),
            diaginertia=_vec(link["inertia"]),
        )
        add_geoms(body, link_name)
        for joint in children.get(link_name, []):
            child = add_body(body, joint["child"], joint["pos"])
            drive = dynamics[joint["name"]]
            ET.SubElement(
                child,
                "joint",
                name=joint["name"],
                type="hinge" if joint["type"] == "revolute" else "slide",
                axis=_vec(joint["axis"]),
                range=_vec(joint["range"]),
                limited="true",
                stiffness=_fmt(drive["stiffness"]),
                damping=_fmt(drive["damping"]),
                frictionloss=_fmt(
                    0.0 if joint["name"] in STICK_TILT_JOINTS else drive["friction"]
                ),
                springref=_fmt(drive["target"]),
            )
        return body

    add_body(worldbody, "controller_body", [0, 0, 0])
    contact = ET.SubElement(root, "contact")
    for trigger_body in ("left_trigger", "right_trigger"):
        ET.SubElement(
            contact,
            "exclude",
            body1="controller_body",
            body2=trigger_body,
        )
    sensor = ET.SubElement(root, "sensor")
    for joint_name in joints:
        ET.SubElement(
            sensor,
            "jointpos",
            name=f"{joint_name}_position",
            joint=joint_name,
        )
    keyframe = ET.SubElement(root, "keyframe")
    ET.SubElement(keyframe, "key", name="neutral", qpos=" ".join("0" for _ in joints))
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(
        output / "xbox_one_s.xml", encoding="utf-8", xml_declaration=False
    )

    scene_root = ET.fromstring(ET.tostring(root))
    scene_world = scene_root.find("worldbody")
    ET.SubElement(
        scene_world,
        "geom",
        name="ground",
        type="plane",
        size="1 1 .1",
        pos="0 0 -0.06",
        rgba=".12 .13 .14 1",
        contype="0",
        conaffinity="0",
    )
    ET.SubElement(
        scene_world,
        "camera",
        name="inspection",
        pos=".12 -.2 .16",
        xyaxes=".86 .51 0 -.32 .54 .78",
        fovy="37",
    )
    ET.indent(scene_root, space="  ")
    ET.ElementTree(scene_root).write(
        output / "scene_fixed.xml", encoding="utf-8", xml_declaration=False
    )

    contact_root = ET.fromstring(ET.tostring(root))
    contact_world = contact_root.find("worldbody")
    probe = ET.SubElement(
        contact_world,
        "body",
        name="left_stick_contact_probe",
        mocap="true",
        pos="-0.0110353599917 0.0241336290442 0.0281238632209",
    )
    ET.SubElement(
        probe,
        "geom",
        name="left_stick_contact_probe_geom",
        type="sphere",
        size="0.006",
        rgba="1 .015 .015 1",
        friction="0.5 0.005 0.0001",
        contype="1",
        conaffinity="1",
        density="0",
    )
    ET.indent(contact_root, space="  ")
    ET.ElementTree(contact_root).write(
        output / "scene_contact_probe.xml", encoding="utf-8", xml_declaration=False
    )

    bindings = {
        "joints": {name: name for name in joints},
        "sensors": {name: f"{name}_position" for name in joints},
    }
    state_mapping = copy.deepcopy(robotwin_manifest["state_mapping"])
    mujoco_neutral_epsilon = float(
        source["signal_policy"]["device_neutral_epsilon"]
    )
    for group in state_mapping["radial_groups"]:
        group["neutral_epsilon"] = mujoco_neutral_epsilon
    state_mapping["neutral_policy"] = {
        "epsilon": mujoco_neutral_epsilon,
        "mode": source["signal_policy"]["device_neutral_mode"],
        "status": "simulation_solver_tolerance_not_hardware_deadzone",
    }

    manifest = {
        "schema_version": 1,
        "asset_id": "xbox_one_s",
        "backend": "mujoco",
        "profile": "full_controls",
        "available": True,
        "dynamics_ready": True,
        "parameter_status": robotwin_manifest["parameter_status"],
        "hardware_calibrated": robotwin_manifest["hardware_calibrated"],
        "entrypoint": "xbox_one_s.xml",
        "required_files": [
            "xbox_one_s.xml", "scene_fixed.xml", "scene_contact_probe.xml"
        ],
        "reason": None,
        "scenes": {
            "fixed": "scene_fixed.xml",
            "contact_probe": "scene_contact_probe.xml"
        },
        "bindings": bindings,
        "state_mapping": state_mapping,
        "source_record": "references/full_controls.json",
        "mechanism_source": "robotwin/full_controls",
        "material_limitations": [
            "MuJoCo sliding friction uses one coefficient; the shared dynamic coefficient 0.4 is used.",
            "The shared restitution estimate has no direct MJCF scalar and remains unmodeled in this first pass."
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": str(output),
        "joints": len(joints),
        "sensors": len(joints),
        "visual_parts": len(part_files),
    }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.output.resolve())


if __name__ == "__main__":
    main()
