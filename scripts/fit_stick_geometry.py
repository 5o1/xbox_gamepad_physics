"""Test whether named stick surfaces support a spherical-center candidate.

No fitted center is automatically promoted to a mechanical pivot. Uses all
vertices, then checks face centroids independently; no hand-picked inliers.
Method reference: scipy.optimize.least_squares official documentation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import scipy
from scipy.optimize import least_squares
import trimesh


def fit_sphere(points, validation):
    points = np.unique(np.asarray(points, dtype=float), axis=0)
    if len(points) < 4 or not np.isfinite(points).all():
        raise ValueError("Insufficient finite vertices")
    origin = points.mean(axis=0)
    scale = float(np.linalg.norm(points - origin, axis=1).max())
    if scale == 0:
        raise ValueError("Zero extent")
    p = (points - origin) / scale
    design = np.column_stack((2 * p, np.ones(len(p))))
    initial, _, rank, singular = np.linalg.lstsq(
        design, (p * p).sum(axis=1), rcond=None
    )
    if rank < 4:
        raise ValueError("Sphere center unidentifiable from coplanar/degenerate points")
    radius2 = initial[3] + initial[:3] @ initial[:3]
    if radius2 <= 0:
        raise ValueError("Invalid algebraic radius")
    fit = least_squares(
        lambda x: np.linalg.norm(p - x[:3], axis=1) - x[3],
        np.r_[initial[:3], np.sqrt(radius2)],
        bounds=([-np.inf] * 3 + [0], [np.inf] * 4),
        method="trf",
        loss="linear",
        ftol=1e-12,
        xtol=1e-12,
        gtol=1e-12,
    )
    if not fit.success:
        raise ValueError("Sphere fit did not converge")
    center = origin + fit.x[:3] * scale
    radius = float(fit.x[3] * scale)
    error = np.linalg.norm(points - center, axis=1) - radius
    independent = np.linalg.norm(np.asarray(validation) - center, axis=1) - radius
    return {
        "candidate_center_m": center.tolist(),
        "candidate_radius_m": radius,
        "vertex_rms_m": float(np.sqrt(np.mean(error**2))),
        "vertex_max_abs_m": float(np.abs(error).max()),
        "centroid_rms_m": float(np.sqrt(np.mean(independent**2))),
        "centroid_max_abs_m": float(np.abs(independent).max()),
        "vertex_relative_rms": float(np.sqrt(np.mean(error**2)) / radius),
        "algebraic_condition_number": float(singular[0] / singular[-1]),
        "solver_evaluations": fit.nfev,
        "mechanical_pivot": None,
        "acceptance_tolerance_m": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest_path = args.asset_dir / "inventory.json"
    manifest = json.loads(manifest_path.read_text())
    names = ("LeftThumb", "RightThumb", "Joystick-Left-Ring", "Joystick-Right-Ring")
    results = []
    for record in manifest["objects"]:
        if record["name"] not in names:
            continue
        path = args.asset_dir / record["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Source hash mismatch")
        mesh = trimesh.load(str(path), force="mesh", process=False)
        # Exact coordinate weld only; no unknown dimensional repair tolerance.
        vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
        mesh = trimesh.Trimesh(
            vertices=vertices, faces=inverse[mesh.faces], process=False
        )
        components = mesh.split(only_watertight=False)
        groups = [("entire_named_object", mesh)]
        if len(components) > 1:
            groups += [
                (f"connected_component_{i}", m) for i, m in enumerate(components)
            ]
        for label, group in groups:
            result = {
                "object": record["name"],
                "source_sha256": record["sha256"],
                "subset": label,
                "vertices": len(group.vertices),
                "triangles": len(group.faces),
            }
            try:
                result.update(fit_sphere(group.vertices, group.triangles_center))
            except ValueError as e:
                result.update(error=str(e), mechanical_pivot=None)
            results.append(result)
    report = {
        "inventory_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "trimesh": trimesh.__version__,
        "method": "Normalized algebraic initialization then geometric radial least squares; full vertices, no inlier rejection; face-centroid check",
        "limitation": "Surface center is not proof of hinge center; visual proxy is not dimensionally verified",
        "results": results,
        "target_pivots_approved": False,
    }
    with args.output.open("x") as out:
        json.dump(report, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
