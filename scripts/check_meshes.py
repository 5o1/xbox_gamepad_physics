"""Audit exported source parts without repairing or changing any mesh.

trimesh topology checks describe geometry only, not physical correctness.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import trimesh


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
        assert hashlib.sha256(path.read_bytes()).hexdigest() == obj["sha256"]
        lines = path.read_text().splitlines()
        raw_vertices = np.array(
            [
                [float(x) for x in line.split()[1:]]
                for line in lines
                if line.startswith("v ")
            ]
        )
        raw_faces = np.array(
            [
                [int(x) - 1 for x in line.split()[1:]]
                for line in lines
                if line.startswith("f ")
            ]
        )
        assert (
            len(raw_vertices) == obj["vertices"] and len(raw_faces) == obj["triangles"]
        )
        assert np.isfinite(raw_vertices).all()
        assert raw_faces.min() >= 0 and raw_faces.max() < len(raw_vertices)
        mesh = trimesh.load(str(path), force="mesh", process=False)
        assert np.isfinite(mesh.vertices).all()
        # Trimesh drops vertices not referenced by any triangle even with process=False.
        # Verify every surface triangle, rather than hiding the difference in counts.
        assert len(mesh.faces) == len(raw_faces)
        assert np.allclose(
            raw_vertices[raw_faces], mesh.vertices[mesh.faces], rtol=0, atol=1e-12
        )
        bounds = np.array([raw_vertices.min(0), raw_vertices.max(0)])
        error = float(np.max(np.abs(bounds - np.array(obj["bounds_native"]))))
        assert error < 1e-7 * max(1.0, float(np.max(np.abs(bounds))))
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
