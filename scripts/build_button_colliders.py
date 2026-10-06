"""Source-preserving convex candidates for ABXY, with explicit shape-change audit."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import scipy
from scipy.spatial import ConvexHull
import trimesh

NAMES = ("A-Button", "B-Button", "X-Button", "Y-Button")


def convex_candidate(mesh):
    # Preserve every point. No random perturbation or tolerance-based merging.
    points = np.unique(mesh.vertices, axis=0)
    hull = ConvexHull(points)
    faces = hull.simplices.copy()
    cross = np.cross(
        points[faces[:, 1]] - points[faces[:, 0]],
        points[faces[:, 2]] - points[faces[:, 0]],
    )
    reverse = (cross * hull.equations[:, :3]).sum(1) < 0
    faces[reverse] = faces[reverse][:, [0, 2, 1]]
    used, inverse = np.unique(faces, return_inverse=True)
    candidate = trimesh.Trimesh(
        vertices=points[used], faces=inverse.reshape(-1, 3), process=False
    )
    if not candidate.is_watertight or not candidate.is_winding_consistent:
        raise ValueError("Convex candidate failed manifold/orientation checks")
    signed = points @ hull.equations[:, :3].T + hull.equations[:, 3]
    tolerance = 128 * np.finfo(float).eps * max(1.0, float(np.abs(points).max()))
    if signed.max() > tolerance:
        raise ValueError("Convex candidate excludes source vertices")
    return candidate, float(signed.max()), tolerance


def sampled_distances(source, target):
    samples = np.concatenate((source.vertices, source.triangles_center))
    distances = []
    closest = []
    triangle_ids = []
    # Batch size is a memory bound, not a geometric parameter.
    for start in range(0, len(samples), 32):
        points, d, ids = trimesh.proximity.closest_point_naive(
            target, samples[start : start + 32]
        )
        distances.extend(d)
        closest.extend(points)
        triangle_ids.extend(ids)
    worst = int(np.argmax(distances))
    return {
        "sample_count": len(samples),
        "max_native": float(np.max(distances)),
        "mean_native": float(np.mean(distances)),
        "exact_hausdorff": False,
        "max_witness": {
            "sample_kind": "vertex"
            if worst < len(source.vertices)
            else "triangle_centroid",
            "sample_index": worst
            if worst < len(source.vertices)
            else worst - len(source.vertices),
            "point_native": samples[worst].tolist(),
            "closest_point_native": closest[worst].tolist(),
            "target_triangle_index": int(triangle_ids[worst]),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("visual_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest_path = args.visual_dir / "inventory.json"
    manifest = json.loads(manifest_path.read_text())
    records = {x["name"]: x for x in manifest["objects"]}
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for name in NAMES:
        record = records[name]
        source_path = args.visual_dir / record["file"]
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Source mesh hash mismatch")
        mesh = trimesh.load(str(source_path), force="mesh", process=False)
        hull, outside, tolerance = convex_candidate(mesh)
        path = args.output / (name + "_convex_candidate.obj")
        hull.export(str(path))
        # Re-load the delivered artifact, not just check the construction object.
        reloaded = trimesh.load(str(path), force="mesh", process=False)
        if not reloaded.is_watertight or not reloaded.is_winding_consistent:
            raise ValueError("Serialized candidate failed checks")
        results.append(
            {
                "source_object": name,
                "source_mesh_sha256": record["sha256"],
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "vertices": len(hull.vertices),
                "faces": len(hull.faces),
                "watertight": bool(reloaded.is_watertight),
                "source_vertex_max_outside_native": outside,
                "numerical_tolerance_native": tolerance,
                "source_to_candidate": sampled_distances(mesh, reloaded),
                "candidate_to_source": sampled_distances(reloaded, mesh),
                "physical_scale": None,
                "mass": None,
                "inertia": None,
                "contact_parameters": None,
                "approved_for_simulation": False,
                "acceptance_threshold": None,
                "limitation": "Hull closes missing surfaces and removes concavities. Exterior/contact fidelity has not been accepted.",
            }
        )
    report = {
        "status": "collision_candidates_not_approved",
        "inventory_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "trimesh": trimesh.__version__,
        "method_record": "sources/collision_method.json",
        "candidates": results,
    }
    (args.output / "collision_audit.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
