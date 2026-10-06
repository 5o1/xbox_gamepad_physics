"""Audit exported source parts without repairing or changing any mesh.

trimesh topology checks describe geometry only, not physical correctness.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import trimesh


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    inventory = json.loads((args.directory / "inventory.json").read_text())
    records = []
    for obj in inventory["objects"]:
        if obj["type"] != "MESH":
            continue
        path = args.directory / obj["file"]
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        require(
            actual_sha256 == obj["sha256"],
            f"{path}: SHA-256 mismatch ({actual_sha256} != {obj['sha256']})",
        )
        lines = path.read_text().splitlines()
        vertex_rows = [
            [float(x) for x in line.split()[1:]]
            for line in lines
            if line.startswith("v ")
        ]
        face_rows = [
            [int(x) - 1 for x in line.split()[1:]]
            for line in lines
            if line.startswith("f ")
        ]
        require(vertex_rows and all(len(row) == 3 for row in vertex_rows), f"{path}: vertices must be non-empty XYZ triples")
        require(face_rows and all(len(row) == 3 for row in face_rows), f"{path}: faces must be non-empty triangles")
        raw_vertices = np.array(vertex_rows)
        raw_faces = np.array(face_rows)
        require(
            len(raw_vertices) == obj["vertices"]
            and len(raw_faces) == obj["triangles"],
            f"{path}: inventory vertex/triangle counts do not match",
        )
        require(bool(np.isfinite(raw_vertices).all()), f"{path}: non-finite source vertex")
        require(
            bool(raw_faces.min() >= 0 and raw_faces.max() < len(raw_vertices)),
            f"{path}: face index outside the source vertex array",
        )
        mesh = trimesh.load(str(path), force="mesh", process=False)
        require(bool(np.isfinite(mesh.vertices).all()), f"{path}: non-finite imported vertex")
        # Trimesh drops vertices not referenced by any triangle even with process=False.
        # Verify every surface triangle, rather than hiding the difference in counts.
        require(len(mesh.faces) == len(raw_faces), f"{path}: imported face count changed")
        require(
            bool(
                np.allclose(
                    raw_vertices[raw_faces],
                    mesh.vertices[mesh.faces],
                    rtol=0,
                    atol=1e-12,
                )
            ),
            f"{path}: imported triangles differ from source triangles",
        )
        bounds = np.array([raw_vertices.min(0), raw_vertices.max(0)])
        error = float(np.max(np.abs(bounds - np.array(obj["bounds_native"]))))
        require(
            error < 1e-7 * max(1.0, float(np.max(np.abs(bounds)))),
            f"{path}: round-trip bounds error {error} exceeds tolerance",
        )
        # OBJ may duplicate coincident vertices at seams. Diagnose with EXACT
        # coordinate equality only; do not select an ungrounded weld tolerance.
        unique, inverse = np.unique(raw_vertices, axis=0, return_inverse=True)
        welded = trimesh.Trimesh(
            vertices=unique, faces=inverse[raw_faces], process=False
        )
        records.append(
            dict(
                name=obj["name"],
                file=obj["file"],
                watertight=bool(mesh.is_watertight),
                exact_weld_watertight=bool(welded.is_watertight),
                exact_weld_winding_consistent=bool(welded.is_winding_consistent),
                exact_duplicate_vertices=len(raw_vertices) - len(unique),
                unused_source_vertices=len(raw_vertices) - len(np.unique(raw_faces)),
                loaded_surface_vertices=len(mesh.vertices),
                winding_consistent=bool(mesh.is_winding_consistent),
                connected_components=len(mesh.split(only_watertight=False)),
                bounds_roundtrip_error_native=error,
                zero_area_triangles=int(np.count_nonzero(mesh.area_faces == 0)),
                physical_mass=None,
                physical_inertia=None,
                collision_approved=False,
            )
        )
    report = dict(
        status="export_integrity_checked_not_contact_validated",
        trimesh_version=trimesh.__version__,
        mesh_objects=len(records),
        objects=records,
        scope="Hashes, finite vertices, face counts, bounds and mesh topology. No repairs, convexification or physical assumptions.",
    )
    (args.directory / "mesh_audit.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "objects"}, indent=2))


if __name__ == "__main__":
    main()
