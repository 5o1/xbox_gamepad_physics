"""Subsystem checks for common-description to native MuJoCo mapping."""
from dataclasses import asdict
import json
from pathlib import Path
import struct
import shutil
import xml.etree.ElementTree as ET

import pytest

from xbox_gamepad_physics.backends.common.appearance import (
    AppearanceDescription, MaterialDescription, TextureDescription, VisualGroup, VisualPart,
)
from xbox_gamepad_physics.backends.common.model import Evidence, Parameter, Pose
from xbox_gamepad_physics.backends.common.physical import LinkPhysical, PhysicalDescription, ReturnLaw
from xbox_gamepad_physics.mujoco.builder import build, resource_node


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def common_root(tmp_path):
    image = pytest.importorskip("PIL.Image")
    root = tmp_path / "resources"
    common = root / "common/xbox_one_s"
    evidence = Evidence("fixture", "definition", "Tiny subsystem fixture, not Xbox parameter evidence.",
                        "Explicit test definition.", category="fixture_definition")
    p = lambda value, unit="1": Parameter(value, unit, (evidence,))
    unknown = lambda unit: Parameter(None, unit, missing_reason="Not identified in fixture.")
    motion = {"asset_id": "xbox_one_s", "profile": "full_controls", "joints": [
        {"name": "a_press", "type": "prismatic", "parent": "controller_body", "child": "a",
         "origin": [0.01, 0, 0], "axis": [0, 0, -1], "lower": 0, "upper": 0.001, "unit": "m"}],
        "bindings": {"scalars": [{"channel": "south", "joint": "a_press"}]}}
    _write(common / "motion/full_controls.json", motion)
    _write(root / "kinematics/xbox_one_s.json", {"nodes": [{"source_node": "button", "joint_ids": ["a_press"]}]})
    links = tuple(LinkPhysical(name, p(.01, "kg"), p([0, 0, 0], "m"),
        p([[1e-6, 0, 0], [0, 1e-6, 0], [0, 0, 1e-6]], "kg*m^2"), name,
        p([1e-6] * 3, "kg*m^2"), p([1, 0, 0, 0])) for name in ("controller_body", "a"))
    law = ReturnLaw(p(0, "m"), p(0, "m"), p(100, "N/m"), p(.1, "N*s/m"), p(.005, "N*s/m"),
        p(-.0001, "m"), p(1, "N"), p(1, "m/s"), p(.01, "kg"), p(.7), unknown("N"), unknown("kg"))
    description = PhysicalDescription("full_controls", "fixture", links, {"a_press": law}, (), "fixture")
    _write(common / "physical/full_controls.json", asdict(description))
    tex = TextureDescription("textures/base.png", "baseColor", "RGBA", "srgb", 0, {}, {}, evidence)
    materials = tuple(MaterialDescription(mode, mode, unknown("1"), p(alpha), False, {}, (tex,), {}, ())
                      for mode, alpha in (("OPAQUE", 1), ("BLEND", 64/255)))
    appearance = AppearanceDescription((VisualPart("button", "unbound", (
        VisualGroup("button.gltf", "OPAQUE", 4), VisualGroup("button.gltf", "BLEND", 4)), Pose(), 1),), materials)
    _write(common / "visual/manifest.json", {"parts": [{"name": "button"}]})
    _write(common / "visual/appearance.json", asdict(appearance))
    (common / "visual/textures").mkdir()
    image.new("RGBA", (2, 2), (80, 100, 120, 64)).save(common / "visual/textures/base.png")
    vertices = [(0, 0, 0), (.005, 0, 0), (0, .005, 0), (0, 0, .005)]
    faces = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
    rows = [vertices, [(0, 0, 1)] * 4, [(0, 0), (1, 0), (0, 1), (1, 1)], [(i,) for f in faces for i in f]]
    views, accessors, raw = [], [], b""
    for values, kind, component, fmt in zip(rows, ("VEC3", "VEC3", "VEC2", "SCALAR"), (5126, 5126, 5126, 5123), ("fff", "fff", "ff", "H")):
        payload = b"".join(struct.pack("<" + fmt, *v) for v in values)
        views.append({"buffer": 0, "byteOffset": len(raw), "byteLength": len(payload)})
        accessors.append({"bufferView": len(views)-1, "componentType": component, "count": len(values), "type": kind})
        raw += payload
    (common / "visual/mesh.bin").write_bytes(raw)
    _write(common / "visual/button.gltf", {"buffers": [{"uri": "mesh.bin", "byteLength": len(raw)}],
        "bufferViews": views, "accessors": accessors, "meshes": [{"primitives": [
            {"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3}]}]})
    _write(common / "collision/manifest.json", {"units": "m", "components": {"a":
        {"coacd": ["a.obj"], "sdf": [], "hull_count": 2}}})
    lines = ["v " + " ".join(map(str, v)) for v in vertices]
    for name in ("first", "second"):
        lines += ["o " + name, *("f " + " ".join(str(i+1) for i in f) for f in faces)]
    (common / "collision/a.obj").write_text("\n".join(lines) + "\n")
    return root


def test_build_native_geometry_material_and_force_mapping(common_root, tmp_path):
    output = tmp_path / "pad"
    manifest = build(output, resource_root=common_root)
    xml = ET.parse(output / manifest["entrypoint"]).getroot()
    assert xml.find("option") is None
    assert xml.find("worldbody/light") is None
    collision = [g for g in xml.findall(".//geom") if g.get("group") == "3"]
    assert len(collision) == manifest["collision_hull_count"] == 2
    assert len({g.get("mesh") for g in collision}) == 2
    assert all(g.get("contype") == g.get("conaffinity") == "1" for g in collision)
    assert all(list(map(float,g.get('solref').split())) == [.002,1.] for g in collision)
    assert all(float(g.get('solmix')) == 1000000. for g in collision)
    assert all(g.get('solmix') is None for g in xml.findall(".//geom[@group='1']"))
    assert manifest["visual_group_count"] == 2
    assert all((output / name).is_file() for name in manifest["required_files"])
    image = pytest.importorskip("PIL.Image")
    with image.open(output / "textures/base_rgb.png") as texture:
        assert texture.mode == "RGB"
        assert texture.getpixel((0, 0)) == (80, 100, 120)
    blend = xml.find("asset/material[@name='BLEND']")
    assert float(blend.get("rgba").split()[-1]) == pytest.approx(64/255)
    joint = xml.find(".//joint[@name='a_press']")
    assert "frictionloss" not in joint.attrib
    assert "armature" not in joint.attrib
    actuator = xml.find("actuator/general")
    assert list(map(float, actuator.get("gainprm").split())) == [100]
    assert list(map(float, actuator.get("biasprm").split())) == [0, -100, -.1]
    assert manifest["neutral_targets"] == {"a_press": -.0001}
    report = json.loads((output / "mapping_report.json").read_text())
    assert report["return_laws"]["a_press"]["frictionloss"] is None
    assert all(value is None for value in report["contact_physical_mapping"].values())
    # Reusing an explicit output directory must still emit its texture declaration.
    build(output, resource_root=common_root)
    assert ET.parse(output / "xbox_one_s.xml").find("asset/texture[@name='base_rgb']") is not None


def test_compiled_subsystem_force_matches_common_return_law(common_root, tmp_path):
    mj = pytest.importorskip("mujoco")
    import numpy as np
    from xbox_gamepad_physics.backends.common.physical import evaluate_generalized_force, load_physical
    output = tmp_path / "pad"
    manifest = build(output, resource_root=common_root)
    model = mj.MjModel.from_xml_path(str(output / "xbox_one_s.xml"))
    data = mj.MjData(model)
    joint = model.joint("a_press")
    actuator = model.actuator("return_a_press")
    law = load_physical(resource_directory=common_root / "common/xbox_one_s/physical").return_laws["a_press"]
    for q, speed, target in ((.0005, .03, 0), (.0002, -.02, .002), (.0008, 4, -.02)):
        data.qpos[joint.qposadr] = q
        data.qvel[joint.dofadr] = speed
        data.ctrl[actuator.id] = target
        mj.mj_forward(model, data)
        force = evaluate_generalized_force(law, q, speed, target=target)
        assert data.qfrc_actuator[joint.dofadr][0] == pytest.approx(force.drive)
        assert data.qfrc_passive[joint.dofadr][0] == pytest.approx(force.passive)
    fixed = mj.MjModel.from_xml_path(str(output / "scene_fixed.xml"))
    free = mj.MjModel.from_xml_path(str(output / "scene_free.xml"))
    assert fixed.nq == 1 and free.nq == 8
    assert np.isfinite(free.body_inertia).all()


def test_unknown_effort_is_rejected_not_defaulted(common_root, tmp_path):
    path = common_root / "common/xbox_one_s/physical/full_controls.json"
    physical = json.loads(path.read_text())
    physical["return_laws"]["a_press"]["effort_limit"] = {
        "value": None, "unit": "N", "evidence": [], "missing_reason": "No measurement."}
    _write(path, physical)
    with pytest.raises(ValueError, match="effort_limit.*No measurement"):
        build(tmp_path / "pad", resource_root=common_root)


def test_compile_bind_qpos_matches_common_physical_initials(common_root):
    mj = pytest.importorskip("mujoco")
    from xbox_gamepad_physics.backends.common.handle import ResetRequest
    from xbox_gamepad_physics.backends.common.physical import load_physical
    from xbox_gamepad_physics.mujoco import make_spec, load_standalone
    path = common_root / "common/xbox_one_s/physical/full_controls.json"
    physical = json.loads(path.read_text())
    physical["return_laws"]["a_press"]["initial_position"]["value"] = .0003
    _write(path, physical)
    build(common_root / "mujoco/full_controls", resource_root=common_root)
    description = load_physical(resource_directory=path.parent)
    expected = {name: law.initial_position.value for name, law in description.return_laws.items()}
    asset = make_spec(resource_root=common_root)
    model = asset.spec.compile()
    handle = asset.bind(model, mj.MjData(model))
    assert handle.joint_positions() == expected
    handle.set_joint_positions({"a_press": .0008})
    handle.reset(ResetRequest())
    assert handle.joint_positions() == expected
    assert load_standalone(resource_root=common_root).gamepad.joint_positions() == expected


def test_existing_dag_cache_and_invalidation(common_root):
    from xbox_gamepad_physics.builders.build_resources import Node, build as build_dag, node_status
    node = resource_node()
    graph = tuple(Node(name, (str(common_root / path),), (), path,
        lambda out, root, relative=path: shutil.copytree(common_root / relative, out)) for name, path in (
        ("kinematics", "kinematics"), ("common_motion", "common/xbox_one_s/motion"),
        ("common_physical", "common/xbox_one_s/physical"), ("sim_visual", "common/xbox_one_s/visual"),
        ("collision", "common/xbox_one_s/collision"))) + (node,)
    # Prepared fixture upstream nodes are already present; only map the adapter.
    # Running the existing DAG twice must publish a reusable content stamp.
    cache = common_root.parent / "cached"
    build_dag(cache, repo=common_root, graph=graph)
    second = build_dag(cache, repo=common_root, graph=graph)
    assert all(not s["stale"] for s in second)
    path = common_root / "common/xbox_one_s/physical/full_controls.json"
    value = json.loads(path.read_text())
    value["return_laws"]["a_press"]["stiffness"]["value"] = 120
    _write(path, value)
    status = {s["name"]: s for s in node_status(cache, repo=common_root, graph=graph)}
    assert status["mujoco_full_controls"]["stale"]
