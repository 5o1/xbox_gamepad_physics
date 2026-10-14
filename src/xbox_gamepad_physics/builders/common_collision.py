"""Build backend-neutral CoACD and unchanged per-shell SDF geometry in metres."""
from __future__ import annotations

import argparse
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import shutil

import numpy as np
import trimesh

from .paths import ROOT, DATA_ROOT
FROZEN = ROOT / "assets/xbox_one_s/collision_coacd"
MESHBASE = ROOT / "assets/xbox_one_s/collision_meshbase"
POLICY = DATA_ROOT / "references/full_controls.json"
DEFAULT_OUTPUT = ROOT / "build/standalone/common/xbox_one_s/collision"


def read_obj(path):
    vertices, faces = [], []
    for line in Path(path).read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == "v":
            vertices.append([float(x) for x in fields[1:4]])
        elif fields and fields[0] == "f":
            if len(fields) != 4:
                raise ValueError(f"expected triangular mesh: {path}")
            faces.append([int(x) - 1 for x in fields[1:]])
    return np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.int32)


def face_shells(faces):
    """Edge-connected shells, ordered by their first face in the source file."""
    edges, neighbours = {}, [set() for _ in faces]
    for index, face in enumerate(faces):
        for a, b in zip(face, np.roll(face, -1)):
            edges.setdefault(tuple(sorted((int(a), int(b)))), []).append(index)
    for uses in edges.values():
        if len(uses) != 2:
            raise ValueError("meshbase must have exactly two faces per edge")
        a, b = uses
        neighbours[a].add(b)
        neighbours[b].add(a)
    pending, shells = set(range(len(faces))), []
    while pending:
        stack, shell = [min(pending)], []
        while stack:
            index = stack.pop()
            if index in pending:
                pending.remove(index)
                shell.append(index)
                stack.extend(neighbours[index])
        shells.append(np.asarray(sorted(shell), dtype=np.int32))
    return shells


def shell_meshes(path):
    vertices, faces = read_obj(path)
    result = []
    for indices in face_shells(faces):
        selected = faces[indices]
        used, inverse = np.unique(selected, return_inverse=True)
        result.append(trimesh.Trimesh(vertices[used], inverse.reshape(-1, 3), process=False))
    return result


def shell_obj_bytes(path, indices):
    """Retain source vertex text and face order; reindex only the split shell."""
    lines = Path(path).read_text().splitlines(keepends=True)
    vertex_lines = [line for line in lines if line.startswith("v ")]
    _, faces = read_obj(path)
    selected = faces[indices]
    used = np.unique(selected)
    remap = {int(old): new + 1 for new, old in enumerate(used)}
    return ("".join(vertex_lines[i] for i in used) + "".join(
        "f " + " ".join(str(remap[int(i)]) for i in face) + "\n" for face in selected
    )).encode()


def write_hulls(path, hulls):
    lines, offset = [], 0
    for index, (vertices, faces) in enumerate(hulls):
        lines.append(f"o hull_{index}")
        lines.extend("v " + " ".join(format(float(x), ".17g") for x in row) for row in vertices)
        lines.extend("f " + " ".join(str(int(x) + offset + 1) for x in row) for row in faces)
        offset += len(vertices)
    Path(path).write_text("\n".join(lines) + "\n")


def read_frozen(output, *, frozen, policy):
    """Read the approved v0.2.0 hulls; CoACD is never imported here."""
    frozen,output=Path(frozen),Path(output)
    snapshot=json.loads((frozen / "manifest.json").read_text())
    if snapshot["collision_policy"]["coacd"] != policy["coacd"]:
        raise ValueError("CoACD policy differs from approved frozen snapshot; maintainer review required")
    output.mkdir(parents=True,exist_ok=True)
    for component,entry in snapshot["components"].items():
        shutil.copyfile(frozen / entry["file"],output / (component+".obj"))
    return snapshot


def build_sdf(output, *, meshbase):
    """Generate triangle OBJ inputs for SAPIEN's later SDF cooking."""
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    records={}
    for component,relative in json.loads((Path(meshbase)/"manifest.json").read_text())["meshes"].items():
        path=Path(meshbase)/relative;_,faces=read_obj(path);shells=face_shells(faces)
        names=[]
        for k,indices in enumerate(shells):
            name=f"{component}_{k}.obj"
            if len(shells)==1:shutil.copyfile(path,output/name)
            else:(output/name).write_bytes(shell_obj_bytes(path,indices))
            names.append("sdf/"+name)
        records[component]=names
    return records


def build(output=DEFAULT_OUTPUT, *, meshbase=MESHBASE, frozen=FROZEN, policy=POLICY):
    output=Path(output)
    source=json.loads(Path(policy).read_text())["collision_policy"]
    snapshot=read_frozen(output/"coacd",frozen=frozen,policy=source)
    sdf=build_sdf(output/"sdf",meshbase=meshbase)
    manifest={"schema_version":1,"units":"m","coordinate_frame":"simulation",
              "method":source["method"],"coacd":snapshot["coacd"],"sdf":source["sdf"],
              "components":{},"required_files":[]}
    if set(snapshot["components"])!=set(sdf):raise ValueError("frozen CoACD and meshbase component names differ")
    for component,entry in snapshot["components"].items():
        record={k:v for k,v in entry.items() if k!="file"}
        record["sdf"]=sdf[component]
        manifest["components"][component]=record
        manifest["required_files"].extend([*record["coacd"],*record["sdf"]])
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument("--meshbase",type=Path,default=MESHBASE)
    parser.add_argument("--frozen",type=Path,default=FROZEN)
    parser.add_argument("--policy",type=Path,default=POLICY)
    build(**vars(parser.parse_args()))

if __name__=="__main__":main()
