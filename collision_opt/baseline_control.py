"""Minimal raw-sweep prerequisite: neutral controls must not intersect the body.

This is a diagnostic, not the complete protection-space generator. Every motion
sweep includes the neutral control solid, so a substantial neutral intersection
already disproves the required body-versus-raw-sweep negative control.
"""
from pathlib import Path
import json
import time

import manifold3d
import numpy as np
import trimesh

from .distance import TriangleDistance
from .metrics import winding


def solid(mesh):
    """Union independently closed shells; never compose overlapping shells."""
    parts = []
    for part in mesh.split(only_watertight=False):
        result = manifold3d.Manifold(manifold3d.Mesh64(
            np.asarray(part.vertices, dtype=np.float64),
            np.asarray(part.faces, dtype=np.uint64)))
        if result.status() != manifold3d.Error.NoError:
            raise ValueError(f"Invalid closed shell: {result.status()}")
        parts.append(result)
    result = manifold3d.Manifold.batch_boolean(parts, manifold3d.OpType.Add)
    if result.status() != manifold3d.Error.NoError:
        raise ValueError(f"Invalid union: {result.status()}")
    return result


def mesh_of(result):
    data = result.to_mesh64()
    return trimesh.Trimesh(data.vert_properties[:, :3], data.tri_verts,
                           process=False)


def interior_witness(intersection, body, control, budget, seed, threshold):
    """Reproducible interior witness; sampled depth is a lower bound only."""
    mesh = mesh_of(intersection)
    rng = np.random.default_rng(seed)
    candidates = rng.uniform(mesh.bounds[0], mesh.bounds[1], (budget, 3))
    candidates = candidates[winding(candidates, mesh.triangles) > threshold]
    if not len(candidates):
        return None
    # Independently check both original solids rather than trusting the Boolean.
    wb = winding(candidates, body.triangles)
    wc = winding(candidates, control.triangles)
    inside = (wb > threshold) & (wc > threshold)
    candidates, wb, wc = candidates[inside], wb[inside], wc[inside]
    if not len(candidates):
        return None
    distances = TriangleDistance(body.triangles).query(candidates)[0]
    index = int(np.argmax(distances))
    point = candidates[index]
    control_distance = float(TriangleDistance(control.triangles).query(point[None])[0][0])
    return {
        "point_mm": point.tolist(),
        "depth_into_body_mm": float(distances[index]),
        "distance_to_control_boundary_mm": control_distance,
        "interior_ball_radius_lower_bound_mm": min(float(distances[index]), control_distance),
        "body_winding": float(wb[index]), "control_winding": float(wc[index]),
        "accepted_interior_samples": len(candidates),
        "sampling": "uniform intersection AABB; reject unless GWN > threshold in both original unions",
    }


def diagnostic_figures(body, controls, intersections, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection

    views = [("front", (0, 1), 2, 1), ("top", (0, 2), 1, 1),
             ("back", (0, 1), 2, -1)]
    paths = []
    for name, axes, depth, sign in views:
        fig, ax = plt.subplots(figsize=(12, 8))
        entries = []
        for mesh, color, alpha in [(body, "#d4d4d4", 0.3)] + [
                (control, "#6096cc", 0.2) for control in controls.values()] + [
                (hit, "#e53525", 0.85) for hit in intersections.values()]:
            for triangle in mesh.triangles:
                entries.append((sign * triangle[:, depth].mean(), triangle[:, axes], color, alpha))
        entries.sort(key=lambda item: item[0])
        rgba = [matplotlib.colors.to_rgba(item[2], item[3]) for item in entries]
        ax.add_collection(PolyCollection([item[1] for item in entries],
                                         facecolors=rgba, edgecolors="none"))
        for control_name, hit in intersections.items():
            center = hit.centroid[list(axes)]
            ax.annotate(control_name, center, fontsize=7, color="#982010",
                        bbox=dict(facecolor="white", alpha=0.6, edgecolor="none", pad=1))
        ax.autoscale()
        if name == "back":
            ax.invert_yaxis()
        ax.set_aspect("equal")
        ax.set_xlabel("XYZ"[axes[0]] + " (mm)")
        ax.set_ylabel("XYZ"[axes[1]] + " (mm)")
        ax.set_title(f"{name}: raw meshbase neutral intersections (red)\n"
                     "DIAGNOSTIC ONLY - not complete protection spaces")
        ax.text(0.01, 0.01, "Gray: original body; blue: neutral controls; red: exact Boolean intersections",
                transform=ax.transAxes, fontsize=9,
                bbox=dict(facecolor="white", alpha=0.85, edgecolor="none"))
        fig.tight_layout()
        path = output / f"baseline_intersection_{name}.png"
        fig.savefig(path, dpi=170)
        plt.close(fig)
        paths.append(str(path))
    return paths


def run(cfg):
    started = time.perf_counter()
    settings = cfg["baseline_control"]
    meshbase = Path(cfg["inputs"]["meshbase"])
    output = Path(cfg["output"])
    output.mkdir(parents=True, exist_ok=True)
    mesh_output = output / "baseline_intersections"
    mesh_output.mkdir(exist_ok=True)
    motion = json.loads(Path(cfg["inputs"]["motion_contract"]).read_text())
    controls_in_motion = {joint["child"] for joint in motion["joints"]}
    shell_names = settings["shell_components"]
    originals = {}
    for path in sorted(meshbase.glob("*.obj")):
        mesh = trimesh.load(path, force="mesh", process=False)
        mesh.vertices *= 1000  # frozen input is metres; all diagnostics are mm
        originals[path.stem] = mesh
    body_solid = manifold3d.Manifold.batch_boolean(
        [solid(originals[name]) for name in shell_names], manifold3d.OpType.Add)
    body = mesh_of(body_solid)
    controls, intersections, records = {}, {}, []
    tolerance = cfg["protection"]["numerical_tolerance_mm"]
    threshold = cfg["error_field"]["winding_inside_threshold"]
    for index, name in enumerate(sorted(set(originals) - set(shell_names))):
        if name not in controls_in_motion:
            raise ValueError(f"Control {name} is absent from motion contract")
        control_solid = solid(originals[name])
        control = mesh_of(control_solid)
        controls[name] = control
        intersection = body_solid ^ control_solid
        if intersection.status() != manifold3d.Error.NoError:
            raise ValueError(f"Boolean failed for {name}: {intersection.status()}")
        volume = float(intersection.volume())
        witness, mesh_path = None, None
        if not intersection.is_empty() and volume > settings["minimum_volume_mm3"]:
            mesh = mesh_of(intersection)
            intersections[name] = mesh
            mesh_path = mesh_output / f"{name}.obj"
            mesh.export(mesh_path)
            witness = interior_witness(intersection, body, control,
                settings["sample_budget"], settings["seed"] + index, threshold)
        confirmed = witness is not None and witness["interior_ball_radius_lower_bound_mm"] > tolerance
        record = {
            "control": name, "neutral_is_in_joint_ranges": all(
                joint["lower"] <= 0 <= joint["upper"] for joint in motion["joints"]),
            "control_union_volume_mm3": float(control_solid.volume()),
            "intersection_volume_mm3": volume,
            "body_fraction_of_control": volume / control_solid.volume(),
            "intersection_mesh": str(mesh_path) if mesh_path else None,
            "witness": witness, "confirmed_above_numerical_tolerance": confirmed,
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    confirmed = [record["control"] for record in records
                 if record["confirmed_above_numerical_tolerance"]]
    report = {
        "scope": "raw meshbase neutral-solid prerequisite; not complete protection generation or hull acceptance",
        "units": {"length": "mm", "volume": "mm^3"},
        "method": "float64 manifold Boolean; union overlapping closed shells before intersection; no subtraction of body from control",
        "implication": "Every full motion sweep contains the neutral solid. An interior ball whose radius exceeds tolerance and is inside both original solids falsifies the requested raw-sweep negative control.",
        "depth_definition": "maximum sampled interior point distance to original body-union boundary; lower bound, not continuous maximum or minimum separating translation",
        "negative_control_passed": not bool(confirmed),
        "confirmed_controls": confirmed, "config": cfg, "controls": records,
        "figures": diagnostic_figures(body, controls, intersections, output),
        "elapsed_seconds": time.perf_counter() - started,
        "primary_docs": [
            "https://manifoldcad.org/docs/html/classmanifold_1_1_manifold.html",
            "https://manifoldcad.org/docs/html/classmanifold_1_1_cross_section.html"],
    }
    (output / "baseline_control.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"negative_control_passed": report["negative_control_passed"],
                      "confirmed_controls": confirmed}, ensure_ascii=False), flush=True)
    return 0 if report["negative_control_passed"] else 3
