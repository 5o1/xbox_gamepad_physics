"""Source material and visual-group semantics; renderer slots stay in adapters."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Mapping
from .model import Evidence, Parameter, Pose


@dataclass(frozen=True)
class TextureDescription:
    resource: str
    role: str
    channels: str
    color_space: str
    uv_set: int
    sampler: Mapping[str, object]
    transform: Mapping[str, object]
    evidence: Evidence


@dataclass(frozen=True)
class MaterialDescription:
    name: str
    alpha_mode: str
    alpha_cutoff: Parameter
    constant_coverage: Parameter
    double_sided: bool
    factors: Mapping[str, Parameter]
    textures: tuple[TextureDescription, ...]
    source_extensions: Mapping[str, object]
    unresolved_differences: tuple[str, ...]


@dataclass(frozen=True)
class VisualGroup:
    geometry_resource: str
    material: str
    triangles: int


@dataclass(frozen=True)
class VisualPart:
    name: str
    link: str
    groups: tuple[VisualGroup, ...]
    local_pose: Pose
    meters_per_native_unit: float


@dataclass(frozen=True)
class AppearanceDescription:
    parts: tuple[VisualPart, ...]
    materials: tuple[MaterialDescription, ...]
    approved_reference: str = "assets/xbox_one_s/approved_render.json"


def _evidence(locator):
    return Evidence("assets/xbox_one_s/visual_meshbase/materials.json",locator,
                    "Approved Xbox One S appearance; not a physical material measurement.",
                    "Preserve reviewed source factors, channel semantics and glTF-defined defaults.",
                    category="fixture_definition")


def group_opacity(manifest, alpha_mode):
    return manifest.get("constant_opacity",{}).get("value",1) if alpha_mode == "BLEND" else 1


def part_records(manifest):
    return {part["name"]:part for part in manifest["parts"]}


def visual_assignments(binding, parts):
    assignments = {name:(binding["root_link"],None) for name in binding["static_parts"]}
    for name,record in binding["moving_parts"].items():
        assignments[name] = (record["link"],record["pivot_m_source_frame"])
    if set(assignments) != set(parts):
        raise ValueError("visual binding part mismatch: "
                         f"missing={sorted(set(parts)-set(assignments))}, "
                         f"extra={sorted(set(assignments)-set(parts))}")
    return assignments


def appearance_from_manifest(manifest, *, materials=None, binding=None):
    """Describe both authored and reviewed sources, preserving their discrepancy."""
    source = manifest.get("source_material",{})
    frozen = materials or {}
    pbr = source.get("pbrMetallicRoughness",{})
    extensions = source.get("extensions",{})
    specular = extensions.get("KHR_materials_specular",{})
    factor_values = {
        "baseColor":pbr.get("baseColorFactor",[1,1,1,1]),
        "metallic":pbr.get("metallicFactor",1), "roughness":pbr.get("roughnessFactor",1),
        "normalScale":source.get("normalTexture",{}).get("scale",1),
        "occlusionStrength":source.get("occlusionTexture",{}).get("strength",1),
        "emissive":source.get("emissiveFactor",[0,0,0]),
        "emissiveStrength":extensions.get("KHR_materials_emissive_strength",{}).get("emissiveStrength",1),
        "specularFactor":specular.get("specularFactor",1),
        "specularColorFactor":specular.get("specularColorFactor",[1,1,1]),
    }
    roles = (("baseColor","base_color.png","RGBA","srgb_rgb_linear_alpha","baseColorTexture"),
             ("metallicRoughness","metallic_roughness.png","G=roughness,B=metallic,R=occlusion","linear","metallicRoughnessTexture"),
             ("emissive","emissive.png","RGB","srgb","emissiveTexture"),
             ("normal","normal.png","RGB tangent-space normal","linear","normalTexture"),
             ("specular","specular_intensity.png","A","linear","specularTexture"))
    files = {item["file"] for item in manifest.get("source_textures",())}
    textures = []
    for role,name,channels,color,slot in roles:
        resource = "textures/"+name
        if resource not in files:
            continue
        slot_record = pbr.get(slot,source.get(slot,specular.get(slot,{})))
        textures.append(TextureDescription(resource,role,channels,color,slot_record.get("texCoord",0),
                                           dict(frozen.get("samplers",[{}])[0]),
                                           dict(slot_record.get("extensions",{}).get("KHR_texture_transform",{})),
                                           _evidence("texture_roles."+role)))
    notes = (frozen.get("specular_note", "Reviewed STATIC_VISUAL uses RGB specularColorTexture; author GLB uses A specularTexture. Reconciliation is deferred."),)
    described = []
    for mode in ("OPAQUE","BLEND"):
        described.append(MaterialDescription(mode,mode,
            Parameter(None,"1",missing_reason="MASK alpha cutoff is not applicable to these groups."),
            Parameter(group_opacity(manifest,mode),"1",(_evidence("constant_opacity"),)),
            source.get("doubleSided",False),
            {name:Parameter(value,"1",(_evidence("authored_material."+name),)) for name,value in factor_values.items()},
            tuple(textures),{"author":extensions,"reviewed_static":frozen.get("authored_material",{}).get("extensions",{}),
                             "reviewed_factors":frozen.get("factors",{}),
                             "reviewed_texture_roles":frozen.get("texture_roles",{})},notes))
    assignments = visual_assignments(binding,part_records(manifest)) if binding is not None else {}
    scale = manifest["meters_per_native_unit"]
    if scale is None or not isinstance(scale,(int,float)) or not math.isfinite(scale) or scale<=0:
        raise ValueError("appearance requires the approved kinematics-derived metres-per-native-unit scale")
    conversion = (math.sqrt(.5),math.sqrt(.5),0,0)
    parts = []
    for item in manifest["parts"]:
        link,pivot = assignments.get(item["name"],("unbound",None))
        pose = Pose(tuple(-float(v) for v in pivot) if pivot is not None else (0,0,0),conversion)
        groups = item.get("groups",[{"file":item["file"],"alpha_mode":"OPAQUE","triangles":item.get("triangles",0)}])
        parts.append(VisualPart(item["name"],link,tuple(VisualGroup(g["file"],g["alpha_mode"],g.get("triangles",0)) for g in groups),pose,scale))
    return AppearanceDescription(tuple(parts),tuple(described))


def write_appearance(directory, *, materials=None):
    root = Path(directory)
    manifest = json.loads((root/"manifest.json").read_text())
    description = appearance_from_manifest(manifest,materials=materials)
    (root/"appearance.json").write_text(json.dumps(asdict(description),indent=2)+"\n")


def load_appearance(profile="full_controls", *, directory=None, binding=None):
    if directory is None:
        from ...resources import resource_path
        directory = resource_path("common","xbox_one_s","visual/manifest.json").parent
    root = Path(directory)
    manifest = json.loads((root/"manifest.json").read_text())
    sidecar = root/"appearance.json"
    if not sidecar.is_file():
        return appearance_from_manifest(manifest,binding=binding)
    value = json.loads(sidecar.read_text())
    materials = []
    for record in value["materials"]:
        textures = tuple(TextureDescription(**{**item,"evidence":Evidence(**{**item["evidence"],
                           "assumptions":tuple(item["evidence"].get("assumptions",()))})}) for item in record["textures"])
        materials.append(MaterialDescription(record["name"],record["alpha_mode"],
            Parameter.from_dict(record["alpha_cutoff"]),Parameter.from_dict(record["constant_coverage"]),
            record["double_sided"],{k:Parameter.from_dict(v) for k,v in record["factors"].items()},
            textures,record["source_extensions"],tuple(record["unresolved_differences"])))
    assignments = visual_assignments(binding,part_records(manifest)) if binding is not None else {}
    parts = []
    for record in value["parts"]:
        local = record["local_pose"]
        pose = Pose(tuple(local["position_m"]),tuple(local["orientation_wxyz"]))
        link = record["link"]
        if binding is not None:
            link,pivot = assignments[record["name"]]
            pose = Pose(tuple(-float(v) for v in pivot) if pivot is not None else (0,0,0),pose.orientation_wxyz)
        parts.append(VisualPart(record["name"],link,tuple(VisualGroup(**item) for item in record["groups"]),
                                pose,record["meters_per_native_unit"]))
    return AppearanceDescription(tuple(parts),tuple(materials),value["approved_reference"])


def derive_texture_channels(source: TextureDescription, channels: str, *, output: Path, directory: Path | None = None):
    from PIL import Image
    if channels not in {"RGB","R","G","B","A"}:
        raise ValueError("expected RGB or one RGBA channel")
    resource = Path(source.resource)
    if not resource.is_absolute() and directory is None:
        raise ValueError("relative texture resources require their explicit visual directory")
    resource = resource if resource.is_absolute() else Path(directory)/resource
    with Image.open(resource) as image:
        converted = image.convert("RGB") if channels == "RGB" else image.convert("RGBA").getchannel(channels)
        output.parent.mkdir(parents=True,exist_ok=True)
        converted.save(output)
    return TextureDescription(str(output),source.role,channels,source.color_space,
                              source.uv_set,source.sampler,source.transform,source.evidence)


def bind_appearance_to_motion(description, kinematics, motion):
    """Bind reviewed part identities from common kinematics to neutral links.

    Geometry is still in authored glTF coordinates. Its scale is applied by
    the consumer; this pose converts Y-up to simulation Z-up, then into the
    complete neutral link frame, including any public origin rotation.
    """
    from dataclasses import replace
    from .transforms import compose, inverse, neutral_link_poses
    poses = neutral_link_poses(motion)
    joints = {joint.name: joint for joint in motion.joints}
    nodes = {node["source_node"]: node for node in kinematics["nodes"]}
    if set(nodes) != {part.name for part in description.parts}:
        raise ValueError("kinematics and appearance part identities differ")
    conversion = Pose(orientation_wxyz=(math.sqrt(.5), math.sqrt(.5), 0., 0.))
    parts = []
    for part in description.parts:
        node = nodes[part.name]
        link = joints[node["joint_ids"][-1]].child if node["joint_ids"] else "controller_body"
        parts.append(replace(part, link=link, local_pose=compose(inverse(poses[link]), conversion)))
    return replace(description, parts=tuple(parts))
