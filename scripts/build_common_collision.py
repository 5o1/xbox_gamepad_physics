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

ROOT = Path(__file__).resolve().parents[1]
MESHBASE = ROOT / "assets/xbox_one_s/collision_meshbase"
POLICY = ROOT / "references/full_controls.json"
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


def build(output=DEFAULT_OUTPUT, *, meshbase=MESHBASE, policy=POLICY):
    os.environ["OMP_NUM_THREADS"] = "1"
    import coacd

    version = importlib.metadata.version("coacd")
    source = json.loads(Path(policy).read_text())["collision_policy"]
    if version != source["coacd"]["version"]:
        raise ValueError(f"requires coacd {source['coacd']['version']}; found {version}")
    output, meshbase = Path(output), Path(meshbase)
    for folder in ("coacd", "sdf"):
        (output / folder).mkdir(parents=True, exist_ok=True)
    defaults = {name: p.default for name, p in inspect.signature(coacd.run_coacd).parameters.items() if name != "mesh"}
    parameters = {**defaults, **source["coacd"]["parameters"]}
    manifest = {"schema_version": 1, "units": "m", "coordinate_frame": "simulation",
                "method": source["method"], "coacd": {"version": version, "parameters": parameters, "threads": 1},
                "sdf": source["sdf"], "components": {}, "required_files": []}
    meshes = json.loads((meshbase / "manifest.json").read_text())["meshes"]
    for component, relative in meshes.items():
        path = meshbase / relative
        vertices, faces = read_obj(path)
        shells, hulls, settings, sdf_files = face_shells(faces), [], [], []
        if component in {"left_stick", "right_stick"} and [len(s) for s in shells] != [350, 336]:
            raise ValueError(f"{component}: expected main/ring shells with 350/336 faces")
        for k, indices in enumerate(shells):
            selected = faces[indices]
            used, inverse = np.unique(selected, return_inverse=True)
            threshold = source["coacd"]["thresholds"].get(component, [0.05] * len(shells))[k]
            config = {**parameters, "threshold": threshold}
            parts = coacd.run_coacd(coacd.Mesh(vertices[used], inverse.reshape(-1, 3).astype(np.int32)), **config)
            hulls.extend(parts)
            settings.append({"shell": k, "face_count": len(indices), "threshold": threshold, "hull_count": len(parts)})
            sdf_file = f"sdf/{component}_{k}.obj"
            if len(shells) == 1:
                shutil.copyfile(path, output / sdf_file)
            else:
                (output / sdf_file).write_bytes(shell_obj_bytes(path, indices))
            sdf_files.append(sdf_file)
        coacd_file = f"coacd/{component}.obj"
        write_hulls(output / coacd_file, hulls)
        manifest["components"][component] = {
            "coacd": [coacd_file], "sdf": sdf_files, "shell_count": len(shells),
            "hull_count": len(hulls), "max_hull_vertices": max(len(v) for v, _ in hulls), "shells": settings,
        }
        manifest["required_files"].extend([coacd_file, *sdf_files])
        print(f"{component}: {len(shells)} shells, {len(hulls)} hulls", flush=True)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meshbase", type=Path, default=MESHBASE)
    parser.add_argument("--policy", type=Path, default=POLICY)
    args = parser.parse_args()
    build(**vars(args))


if __name__ == "__main__":
    main()
