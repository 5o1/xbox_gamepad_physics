"""Frozen hull and triangle-shell sources, independent of engine cooking."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable
from .model import Pose
from .transforms import inverse, neutral_link_poses


@dataclass(frozen=True)
class HullSource:
    resource: str
    object_name: str | None
    source_identity: str


@dataclass(frozen=True)
class CollisionSource:
    component: str
    convex_hulls: tuple[HullSource, ...]
    triangle_shells: tuple[str, ...]
    root: Path
    frame: str = "simulation"
    unit: str = "m"
    evidence: tuple[str, ...] = ("assets/xbox_one_s/collision_coacd/manifest.json",)
    limitations: tuple[str, ...] = ("Triangle shells are cooking inputs, not cooked SDF data.",)


@dataclass(frozen=True)
class FrozenHull:
    hull_id: str
    component: str
    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, int, int], ...]
    local_pose: Pose
    source: HullSource


@dataclass(frozen=True)
class CollisionInstance:
    component: str
    link: str
    source: CollisionSource
    source_to_link: Pose


@dataclass(frozen=True)
class ContactPolicy:
    disabled_internal_pairs: tuple[tuple[str, str], ...]
    external_roles: tuple[str, ...] = ("support", "tool", "environment")
    environment_isolation: bool = True
    inter_instance_policy: str = "caller_defined"

    def instance_pairs(self, instance_id: str):
        return tuple(((instance_id,a),(instance_id,b)) for a,b in self.disabled_internal_pairs)


def _objects(path: Path):
    vertices, groups, current = [], [], None
    for line in path.read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "v":
            vertices.append(tuple(float(x) for x in fields[1:4]))
        elif fields[0] == "o":
            current = [" ".join(fields[1:]), []]
            groups.append(current)
        elif fields[0] == "f":
            if len(fields) != 4:
                raise ValueError(f"frozen hull is not triangular: {path}")
            if current is None:
                current = [None, []]
                groups.append(current)
            face = []
            for field in fields[1:]:
                index = int(field.split("/")[0])
                face.append(index-1 if index>0 else len(vertices)+index)
            current[1].append(tuple(face))
    for name, faces in groups:
        if not faces:
            continue
        used = sorted({index for face in faces for index in face})
        if not used or used[0]<0 or used[-1]>=len(vertices):
            raise ValueError(f"invalid frozen hull vertex index: {path}")
        remap = {old:new for new,old in enumerate(used)}
        yield name, tuple(vertices[i] for i in used), tuple(tuple(remap[i] for i in f) for f in faces)


def load_collision_sources(profile="full_controls", *, directory=None):
    if directory is None:
        from ...resources import resource_path
        directory = resource_path("common", "xbox_one_s", "collision/manifest.json").parent
    root = Path(directory)
    manifest = json.loads((root/"manifest.json").read_text())
    if manifest.get("units") != "m":
        raise ValueError("collision sources must use metres")
    result = []
    for component, record in manifest["components"].items():
        hulls = tuple(HullSource(relative, name, f"frozen-v0.2.0:{component}:{name}")
                      for relative in record["coacd"] for name,_,_ in _objects(root/relative))
        if len(hulls) != record["hull_count"]:
            raise ValueError(f"{component}: frozen hull count differs from manifest")
        result.append(CollisionSource(component,hulls,tuple(record["sdf"]),root))
    return tuple(result)


def iter_frozen_hulls(source: CollisionSource) -> Iterable[FrozenHull]:
    for resource in dict.fromkeys(h.resource for h in source.convex_hulls):
        declared = {h.object_name:h for h in source.convex_hulls if h.resource == resource}
        for name,vertices,faces in _objects(source.root/resource):
            evidence = declared[name]
            yield FrozenHull(evidence.source_identity,source.component,vertices,faces,Pose(),evidence)


def bind_collision_to_links(sources, motion):
    poses = neutral_link_poses(motion)
    parents = {j.parent for j in motion.joints}
    final = {j.child for j in motion.joints if j.child not in parents}
    result = []
    for source in sources:
        link = "controller_body" if source.component in {"shell","shell_front_plate"} else source.component
        if link not in poses or (link != "controller_body" and link not in final):
            raise ValueError(f"collision component has no final motion link: {source.component}")
        result.append(CollisionInstance(source.component,link,source,inverse(poses[link])))
    return tuple(result)


def internal_contact_policy(motion):
    links = ("controller_body",)+tuple(j.child for j in motion.joints)
    return ContactPolicy(tuple((a,b) for i,a in enumerate(links) for b in links[i+1:]))


def select_collision_files(records, selection):
    if selection not in {"coacd", "sdf"}:
        raise ValueError("collision must be 'coacd' or 'sdf'")
    return {name:tuple(record[selection]) for name,record in records.items()}


def selected_collision_variant(variants, selection):
    """Select declared geometry/cooking policy without silently substituting it."""
    if selection not in {"coacd", "sdf"}:
        raise ValueError("collision must be 'coacd' or 'sdf'")
    return variants.get(selection)
