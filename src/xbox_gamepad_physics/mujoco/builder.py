"""Map prepared common assets to native MuJoCo resources without engine imports."""
from __future__ import annotations

import copy
import shutil
from dataclasses import asdict
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

from ..backends.common.appearance import derive_texture_channels, load_appearance
from ..backends.common.collision import (
    bind_collision_to_links, internal_contact_policy, iter_frozen_hulls,
    load_collision_sources,
)
from ..backends.common.physical import load_physical
from ..backends.common.transforms import compose
from ..motion import motion_from_dict
from .numerics import (numerical_policy, contact_policy, sdf_policy, limit_policy,
                       standalone_option_attributes, standalone_flag_attributes, POLICY_RESOURCE)
from .limits import append_native_tilt_limits

SUPPORTED_VERSION = "3.16.0"
CONTACT_NUMERICS = {
    "friction": [1, 0.005, 0.0001], "condim": 3,
    "solref": [0.02, 1], "solimp": [0.9, 0.95, 0.001, 0.5, 2],
    "margin": 0, "gap": 0,
}
XML_REFERENCE = "https://github.com/google-deepmind/mujoco/blob/3.16.0/doc/XMLreference.rst"


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _vec(values):
    return " ".join(format(float(v), ".17g") for v in values)


def _number(parameter, field):
    if parameter.value is None:
        raise ValueError(f"MuJoCo mapping requires {field}: {parameter.missing_reason}")
    return float(parameter.value)


def _accessor(document, index, directory):
    """Read exported glTF accessors, retaining UV/normal indexing and float values."""
    accessor = document["accessors"][index]
    if "sparse" in accessor or accessor.get("normalized", False):
        raise ValueError("prepared visual accessor must be dense and unnormalized")
    view = document["bufferViews"][accessor["bufferView"]]
    buffer = document["buffers"][view["buffer"]]
    uri = Path(buffer["uri"])
    if uri.is_absolute() or ".." in uri.parts:
        raise ValueError("prepared visual buffer must be relative to its directory")
    raw = (directory / uri).read_bytes()
    formats = {5121: "B", 5123: "H", 5125: "I", 5126: "f"}
    widths = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    fmt = "<" + formats[accessor["componentType"]] * widths[accessor["type"]]
    width = struct.calcsize(fmt)
    stride = view.get("byteStride", width)
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    return [struct.unpack_from(fmt, raw, offset + i * stride) for i in range(accessor["count"])]


def _visual_obj(source, destination):
    """Export one common primitive to OBJ; no welding, remeshing or normal repair."""
    document = _json(source)
    primitives = document["meshes"][0]["primitives"]
    if len(primitives) != 1:
        raise ValueError("a prepared visual group must contain exactly one primitive")
    primitive = primitives[0]
    if primitive.get("mode", 4) != 4:
        raise ValueError("prepared visual group must contain triangles")
    attributes = primitive["attributes"]
    position = _accessor(document, attributes["POSITION"], source.parent)
    uv = _accessor(document, attributes["TEXCOORD_0"], source.parent)
    normal = _accessor(document, attributes["NORMAL"], source.parent)
    indices = [v[0] for v in _accessor(document, primitive["indices"], source.parent)]
    if len(indices) % 3 or len(position) != len(uv) or len(position) != len(normal):
        raise ValueError("prepared visual group indexing is inconsistent")
    lines = ["# Prepared common visual group; original vertex/UV/normal values preserved."]
    lines += ["v " + _vec(v) for v in position]
    lines += ["vt " + _vec(v) for v in uv]
    lines += ["vn " + _vec(v) for v in normal]
    for start in range(0, len(indices), 3):
        face = [i + 1 for i in indices[start:start+3]]
        if min(face) < 1 or max(face) > len(position):
            raise ValueError("prepared visual group index is out of bounds")
        lines.append("f " + " ".join(f"{i}/{i}/{i}" for i in face))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_xml(path, root):
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def resource_node():
    """Return the existing DAG's adapter node; registration belongs to composition."""
    from ..builders.build_resources import Node
    package = Path(__file__).resolve().parents[1]
    sources = (str(Path(__file__).resolve()), str(Path(__file__).with_name('numerics.py')),
               str(Path(__file__).with_name('limits.py')),
               str(POLICY_RESOURCE), str(package / "motion.py"),
               *(str(package / "backends/common" / name) for name in
                 ("model.py", "appearance.py", "collision.py", "physical.py", "transforms.py")))
    return Node("mujoco_full_controls", (),
                ("kinematics", "common_motion", "common_physical", "sim_visual", "collision"),
                "mujoco/full_controls", lambda out, root: build(out, resource_root=root),
                sources, json.dumps({"mujoco": SUPPORTED_VERSION, "contact_numerics": CONTACT_NUMERICS}, sort_keys=True))


def build(output: Path, *, resource_root: Path, kinematics: Path | None = None):
    """Build ``mujoco/full_controls`` from all four prepared common descriptions.

    Cache and invalidation are owned by ``resource_node`` and the shared DAG.
    This function neither prepares upstream assets nor invokes an engine/cooker.
    """
    from ..backends.common.appearance import bind_appearance_to_motion
    output, resource_root = Path(output), Path(resource_root)
    common = resource_root / "common/xbox_one_s"
    raw_motion = _json(common / "motion/full_controls.json")
    motion = motion_from_dict(raw_motion)
    hard_limits = [dict(item) for item in motion.joint_space_constraints
                   if item.get('enforcement') == 'hard']
    if any(item['type'] != 'shaft_tilt_limit' for item in hard_limits):
        raise ValueError('MuJoCo does not implement this public hard mechanical constraint')
    cone_joints = {name for item in hard_limits for name in item['joint_ids']}
    physical = load_physical(resource_directory=common / "physical")
    calibration_path = common / 'physical/full_controls.calibration.json'
    configured = _json(calibration_path).get('backend_options', {}).get('mujoco') if calibration_path.is_file() else None
    numerics = numerical_policy(configured)
    response = contact_policy(configured)
    sdf = sdf_policy(configured)
    limit_response = limit_policy(configured)
    collision_numerics = {**CONTACT_NUMERICS,
        'solref': [response['solref_time_constant_s'], response['solref_damping_ratio']],
        'solmix': response['solmix_weight']}
    appearance = bind_appearance_to_motion(load_appearance(directory=common / "visual"),
        _json(kinematics or resource_root / "kinematics/xbox_one_s.json"), motion)
    collision = bind_collision_to_links(load_collision_sources(directory=common / "collision"), motion)
    policy = internal_contact_policy(motion)
    output.mkdir(parents=True, exist_ok=True)
    xml = ET.Element("mujoco", model="xbox_one_s_full_controls")
    ET.SubElement(xml, "compiler", angle="radian", inertiafromgeom="false", balanceinertia="false")
    assets = ET.SubElement(xml, "asset")
    world = ET.SubElement(xml, "worldbody")
    bodies = {"controller_body": ET.SubElement(world, "body", name="controller_body")}
    pending = list(motion.joints)
    while pending:
        ready = [j for j in pending if j.parent in bodies]
        if not ready:
            raise ValueError("motion body tree is disconnected or cyclic")
        for joint in ready:
            bodies[joint.child] = ET.SubElement(bodies[joint.parent], "body", name=joint.child,
                pos=_vec(joint.origin), quat=_vec(joint.origin_orientation_wxyz))
            pending.remove(joint)
    link_physics = {link.name: link for link in physical.links}
    if set(link_physics) != set(bodies):
        raise ValueError("common physical link names differ from motion body tree")
    for name, body in bodies.items():
        link = link_physics[name]
        if link.frame != name:
            raise ValueError(f"{name}: inertia is not expressed in its link frame")
        tensor = link.inertia_com_kg_m2.value
        if tensor is None or link.com_m.value is None:
            raise ValueError(f"{name}: common COM/inertia are missing")
        ET.SubElement(body, "inertial", pos=_vec(link.com_m.value),
            mass=_vec([_number(link.mass_kg, name + '.mass')]),
            fullinertia=_vec([tensor[0][0], tensor[1][1], tensor[2][2], tensor[0][1], tensor[0][2], tensor[1][2]]))
    actuator = ET.SubElement(xml, "actuator")
    return_mapping, initials, targets = {}, {}, {}
    for joint in motion.joints:
        law = physical.return_laws[joint.name]
        if law.saturation_scope != "drive":
            raise ValueError(f"{joint.name}: unsupported return saturation {law.saturation_scope!r}")
        k = _number(law.stiffness, joint.name + '.stiffness')
        d = _number(law.drive_damping, joint.name + '.drive_damping')
        effort = _number(law.effort_limit, joint.name + '.effort_limit')
        attributes = dict(name=joint.name, type="slide" if joint.kind == "prismatic" else "hinge",
            axis=_vec(joint.axis), limited="false" if joint.name in cone_joints else "true", range=_vec([joint.lower, joint.upper]),
            ref="0", stiffness="0", damping=_vec([_number(law.passive_damping, joint.name + '.passive_damping')]))
        for field, parameter, expected in (("frictionloss", law.dry_friction_effort, "N" if joint.kind == "prismatic" else "N*m"),
                                            ("armature", law.armature, "kg" if joint.kind == "prismatic" else "kg*m^2")):
            if parameter.value is not None:
                if parameter.unit != expected or not parameter.evidence:
                    raise ValueError(f"{joint.name}.{field}: applicable {expected} evidence is required")
                attributes[field] = _vec([parameter.value])
        ET.SubElement(bodies[joint.child], "joint", **attributes)
        ET.SubElement(actuator, "general", name="return_" + joint.name, joint=joint.name,
            gear="1", dyntype="none", gaintype="fixed", gainprm=_vec([k]),
            biastype="affine", biasprm=_vec([0, -k, -d]), ctrllimited="false",
            forcelimited="true", forcerange=_vec([-effort, effort]))
        initials[joint.name] = _number(law.initial_position, joint.name + '.initial_position')
        targets[joint.name] = _number(law.neutral_target, joint.name + '.neutral_target')
        return_mapping[joint.name] = {
            "common": asdict(law), "actuator": "return_" + joint.name,
            "equation": "clip(K*(ctrl-q)-D_drive*qvel, +/-effort_limit) - D_passive*qvel",
            "dry_friction_effort": law.dry_friction_effort.value,
            "frictionloss": law.dry_friction_effort.value,
            "armature": law.armature.value,
            "unmapped": {"velocity_limit": "No equivalent scalar joint velocity constraint; common value is retained.",
                         "dry_friction_effort": law.dry_friction_effort.missing_reason,
                         "armature": law.armature.missing_reason},
            "missing_native_terms": "Null frictionloss/armature are omitted and native zero means disabled, not measured zero.",
        }
    collision_records = []
    for instance in collision:
        for index, hull in enumerate(iter_frozen_hulls(instance.source)):
            name = f"collision_{instance.component}_{index:03d}"
            relative = "meshes/collision/" + name + ".obj"
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("\n".join([*("v " + _vec(v) for v in hull.vertices),
                *("f " + " ".join(str(i+1) for i in face) for face in hull.faces)]) + "\n")
            ET.SubElement(assets, "mesh", name=name, file=relative)
            pose = compose(instance.source_to_link, hull.local_pose)
            ET.SubElement(bodies[instance.link], "geom", name=name, type="mesh", mesh=name,
                pos=_vec(pose.position_m), quat=_vec(pose.orientation_wxyz),
                group="3", contype="1", conaffinity="1", mass="0", rgba="0.5 0.5 0.5 0",
                **{key: _vec(value) if isinstance(value, list) else str(value) for key, value in collision_numerics.items()})
            collision_records.append({"geom": name, "mesh": relative, "link": instance.link,
                                      "hull_id": hull.hull_id, "source": asdict(hull.source)})
    visual_records = []
    for material in appearance.materials:
        texture = next(t for t in material.textures if t.role == "baseColor")
        relative = "textures/base_rgb.png"
        if assets.find("texture[@name='base_rgb']") is None:
            derive_texture_channels(texture, "RGB", output=output / relative, directory=common / "visual")
            ET.SubElement(assets, "texture", name="base_rgb", type="2d", file=relative, nchannel="3", colorspace="sRGB", vflip="true")
        # Classic Phong has no exact glTF PBR mapping. These explicit coefficients
        # retain the base color and make no claim of material equivalence.
        ET.SubElement(assets, "material", name=material.name, texture="base_rgb",
            rgba=_vec([1, 1, 1, material.constant_coverage.value]),
            specular="0.5", shininess="0.2", reflectance="0", emission="0")
    for part in appearance.parts:
        if part.link not in bodies:
            raise ValueError(f"{part.name}: appearance is not bound to a motion body")
        for index, group in enumerate(part.groups):
            name = f"visual_{part.name}_{index}"
            relative = "meshes/visual/" + name + ".obj"
            _visual_obj(common / "visual" / group.geometry_resource, output / relative)
            ET.SubElement(assets, "mesh", name=name, file=relative, scale=_vec([part.meters_per_native_unit] * 3))
            ET.SubElement(bodies[part.link], "geom", name=name, type="mesh", mesh=name,
                pos=_vec(part.local_pose.position_m), quat=_vec(part.local_pose.orientation_wxyz),
                material=group.material, contype="0", conaffinity="0", mass="0", group="1")
            visual_records.append({"geom": name, "link": part.link, "source": group.geometry_resource,
                                   "material": group.material, "triangles": group.triangles})
    contact = ET.SubElement(xml, "contact")
    for index, (first, second) in enumerate(policy.disabled_internal_pairs):
        ET.SubElement(contact, "exclude", name=f"internal_{index:03d}", body1=first, body2=second)
    native_tilt_limits = append_native_tilt_limits(xml, hard_limits, policy=limit_response)
    # CoACD remains an explicit comparison; native SDF preserves common cavities.
    _write_xml(output / "xbox_one_s_coacd.xml", xml)
    coacd_records = collision_records
    xml = copy.deepcopy(xml)
    assets = xml.find('asset')
    for body in xml.findall('.//body'):
        for geom in list(body.findall("geom[@group='3']")):
            body.remove(geom)
    for record in coacd_records:
        assets.remove(assets.find(f"mesh[@name='{record['geom']}']"))
    sdf_records = []
    for instance in collision:
        if not instance.source.triangle_shells:
            raise ValueError(f'{instance.component}: native SDF requires common triangle shells')
        body = xml.find(f".//body[@name='{instance.link}']")
        for index, shell in enumerate(instance.source.triangle_shells):
            name = f'sdf_{instance.component}_{index:03d}'
            relative = 'meshes/sdf/' + name + '.obj'
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(instance.source.root / shell, destination)
            ET.SubElement(assets, 'mesh', name=name, file=relative)
            pose = instance.source_to_link
            ET.SubElement(body, 'geom', name=name, type='sdf', mesh=name,
                pos=_vec(pose.position_m), quat=_vec(pose.orientation_wxyz),
                group='3', contype='1', conaffinity='1', mass='0', rgba='0.5 0.5 0.5 0',
                **{key: _vec(value) if isinstance(value, list) else str(value) for key, value in collision_numerics.items()})
            sdf_records.append({'geom': name, 'mesh_name': name, 'mesh': relative,
                'link': instance.link, 'component': instance.component,
                'source_shell': str(shell), 'shell_id': f'{instance.component}:{index}',
                'source_to_link': asdict(pose)})
    collision_records = sdf_records
    _write_xml(output / "xbox_one_s.xml", xml)
    for mode in ("fixed", "free"):
        scene = ET.fromstring(ET.tostring(xml))
        scene.set("model", "xbox_one_s_" + mode)
        option = ET.SubElement(scene, "option", **standalone_option_attributes(numerics),
            sdf_iterations=str(sdf['sdf_iterations']), sdf_initpoints=str(sdf['sdf_initpoints']))
        ET.SubElement(option, 'flag', **standalone_flag_attributes(numerics))
        if mode == "free":
            ET.SubElement(scene.find("worldbody/body"), "freejoint", name="root_free")
        _write_xml(output / f"scene_{mode}.xml", scene)
    mapping = {
        "schema_version": 1, "backend": "mujoco", "version": SUPPORTED_VERSION,
        "source": XML_REFERENCE, "configuration_id": physical.configuration_id,
        "backend_options": {'mujoco': {'numerical_stability': numerics, 'contact_response': response, 'sdf': sdf, 'limit_response': limit_response}},
        "return_laws": return_mapping, "contact_materials": [asdict(m) for m in physical.contact_materials],
        "contact_physical_mapping": {"static_friction": None, "dynamic_friction": None, "restitution": None,
                                     "rolling_resistance_length": None, "torsional_resistance_length": None},
        "contact_mapping_reason": "PhysX static/dynamic friction and restitution lack an identified MuJoCo mapping. No parameter equivalence is claimed.",
        "contact_numerical_policy": {"values": collision_numerics, "category": "trial_numerical_contact_policy",
                                     "source": XML_REFERENCE, "derivation": "Explicit native defaults except owner-approved gamepad solref/solmix; no hardware material identification.",
                                     "uncertainty": None, "uncertainty_reason": "No cross-engine material identification experiment is available."},
        "appearance": {"texture_channels": "RGB", "alpha_applications": 1,
            "coverage": {m.name: m.constant_coverage.value for m in appearance.materials},
            "phong_numerical_policy": {"specular": 0.5, "shininess": 0.2, "reflectance": 0, "emission": 0},
            "degradations": ["Classic Phong coefficients are display assumptions, not a lossless glTF PBR mapping.",
                "Metallic/roughness, normal, occlusion, emissive and specular texture roles are preserved upstream but not reproduced by the classic adapter.",
                "Classic transparent-geometry sorting and double-sided rendering differ from the approved Cycles reference."]},
        "joint_space_constraints": [dict(c) for c in motion.joint_space_constraints],
        "joint_space_constraint_mapping": "Shaft cones use native spatial-tendon length limits, solved jointly with contacts. Native compliance does not satisfy the exact common hard-bound guarantee. No post-step state correction. Redundant scalar tilt limits remain disabled; click limits and signal mapping are unchanged.",
        "hard_limits": hard_limits,
        "native_tilt_limits": native_tilt_limits,
        "collision": collision_records, "coacd_comparison": coacd_records, "visual": visual_records,
    }
    _write_json(output / "mapping_report.json", mapping)
    usage = {"entrypoint": "xbox_gamepad_physics.mujoco.load_standalone",
             "example": "import mujoco\nfrom xbox_gamepad_physics.mujoco import load_standalone\nscene = load_standalone(fixed_root=True)\nmujoco.mj_step(scene.model, scene.data)  # Native contacts and tilt limits\n",
             "warning": "Compile through make_spec and bind to preserve materials, collision and signal mappings.",
             "numerical_stability": (
                 f"Standalone and acceptance models use {numerics['integrator']} with physics timestep <= 0.0005 s "
                 f"and refsafe {'enabled' if numerics.get('refsafe', True) else 'disabled'}. "
                 "Buttons have high natural frequencies; frozen 0.004 s acceptance steps contain eight native physics substeps. "
                 "Newton, 100 iterations, tolerance 1e-8 and diagexact disabled retain the selected solver defaults. "
                 "This is a numerical stability policy, not hardware physical properties. Caller-owned options are never overwritten.")}
    usage['contact_response'] = (
        'Gamepad collision geoms carry trial solref=(0.002 s, 1) and solmix=1000000 to limit excessive penetration with default downstream fingers. '
        'The probe retains native defaults. Equal-priority positive solref/solimp mixing is dominated by the gamepad; friction coefficient mixing is unchanged. '
        'Higher priority, direct-format solref, explicit pairs or global contact overrides retain native precedence. '
        'Override through an explicit calibration backend_options.mujoco.contact_response, record your approval/rationale, prepare_resources again and recompile. '
        'Alternatively the caller can edit this asset fragment before compilation; external geoms and global options are never edited. This is a numerical policy, not measured material properties.')
    usage['collision'] = (
        'Native SDF is the default, one instance per common triangle shell; no plugin is needed. '
        'Use collision="coacd" only for an explicit convex-hull comparison. '
        'make_spec sets each SDF mesh octree_maxdepth=8 before compilation (native default 6); '
        'this MjSpec-only setting is not serialized in XML. Direct XML compilation uses native depth 6. '
        'Depth 8 gives nominal finest cells of about 0.6 mm for a 0.15 m shell, not a certified error bound. '
        'Standalone models retain native sdf_iterations=10 and sdf_initpoints=40; attachment preserves caller global options. '
        'Override the SDF policy through backend_options.mujoco.sdf, rebuild and compile with make_spec, '
        'or edit the fragment mesh settings and your own model options before compilation.')
    usage['hard_limits'] = (
        'Circular shaft limits are encoded in MJCF as native spatial-tendon length constraints upstream of click travel. '
        'Use ordinary mujoco.mj_step; scene.step is a convenience wrapper for the same native call. '
        'MuJoCo solves limit reactions together with external contacts, including floating-root coupling. '
        'No position projection, velocity correction or extra impulse is applied after stepping or during reset. '
        'Two massless direction sites per stick use a 1 m mathematical unit-vector embedding, not physical cables. '
        f"The selected native limit solref={tuple(limit_response['solreflimit'])}, solimp={tuple(limit_response['solimplimit'])} "
        'and zero margin are owner-approved numerical response parameters, not identified hardware properties. '
        'Their measured behavior requires the standalone numerical policy; caller models may choose different options, '
        'with actual versus recommended integrator/refsafe/timestep reported in diagnostics. '
        'Override backend_options.mujoco.limit_response in an explicit calibration and rebuild, or edit the instance tendons before compilation. '
        'Native limits are compliant: the exact common hard-bound guarantee is unsupported and reported as an error finding. '
        'Read tilt_limit_state() for actual angles and excess, which are never hidden by state correction. '
        'Out-of-range explicit state writes are rejected. Return laws, click limits, caller options and external geoms are retained.')
    (output / "README.md").write_text(
        "# Generated MuJoCo Xbox One S resources\n\n" + usage["warning"] + "\n\n```python\n" + usage["example"] + "```\n\n"
        "The asset fragment has no global options, lights or cameras. Root fixation is selected before compilation. "
        "Scene files set standalone numerical options only. Bind initializes the instance from common physical initial positions "
        "and neutral targets; default reset restores the same control state. "
        "This artifact is a simulation estimate; contact results are documented separately.\n\n"
        + usage['numerical_stability'] + "\n\n"
        + usage['contact_response'] + "\n\n"
        + usage['collision'] + "\n\n"
        + usage['hard_limits'] + "\n\n"
        "The existing resource DAG invalidates this node when common motion, physical/calibration, visual, collision, "
        "kinematics, adapter source, supported version or mapping policy changes, or any required output is missing. "
        "Frozen collision hulls are never recooked. See mapping_report.json for every mapped/unmapped parameter.\n", encoding="utf-8")
    required = sorted(p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file())
    manifest = {"schema_version": 1, "asset_id": "xbox_one_s", "backend": "mujoco", "profile": "full_controls",
        "hardware_calibrated": False,
        "reason": None,
        "backend_options": {'mujoco': {'numerical_stability': numerics, 'contact_response': response, 'sdf': sdf, 'limit_response': limit_response}},
        "entrypoint": "xbox_one_s.xml", "default_collision": "sdf",
        "collision_variants": {
            "sdf": {"entrypoint": "xbox_one_s.xml", "mesh_names": [r['mesh_name'] for r in sdf_records],
                    "geoms": [r['geom'] for r in sdf_records], "shell_count": len(sdf_records)},
            "coacd": {"entrypoint": "xbox_one_s_coacd.xml", "mesh_names": [r['geom'] for r in coacd_records],
                      "geoms": [r['geom'] for r in coacd_records], "hull_count": len(coacd_records), "comparison_only": True}},
        "scenes": {"fixed": "scene_fixed.xml", "free": "scene_free.xml"},
        "required_files": required, "mujoco_version": SUPPORTED_VERSION,
        "motion_contract": "common/xbox_one_s/motion/full_controls.json", "root_body": "controller_body",
        "bindings": {"joints": {j.name: j.name for j in motion.joints}, "sensors": {},
                     "actuators": {j.name: "return_" + j.name for j in motion.joints},
                     "bodies": {name: name for name in bodies}, "root_body": "controller_body", "root_joint": "root_free"},
        "initial_positions": initials, "neutral_targets": targets,
        "collision_geoms": [r["geom"] for r in collision_records], "visual_geoms": [r["geom"] for r in visual_records],
        "collision_shell_count": len(sdf_records), "collision_hull_count": len(coacd_records), "visual_group_count": len(visual_records),
        "contact_policy": asdict(policy), "mapping_report": "mapping_report.json", "usage": usage,
        "hard_limits": hard_limits,
        "native_tilt_limits": native_tilt_limits,
        "capabilities": {"birth_fixed_free": True, "runtime_root_switch": False,
                         "named_target_drive": True,
                         "native_shaft_tilt_limits": bool(native_tilt_limits),
                         "hard_shaft_limits": False, "native_mj_step_hard_shaft_limits": False,
                         "post_step_state_correction": False},
    }
    _write_json(output / "manifest.json", manifest)
    return manifest
