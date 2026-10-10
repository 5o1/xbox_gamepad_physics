"""Compare existing hulls with all named button layers, without changing assets.

Names are visual grouping evidence, not proof of mechanical connectivity.
Distance algorithm: https://trimesh.org/trimesh.proximity.html#trimesh.proximity.closest_point_naive
"""

import argparse
import hashlib
import json
from pathlib import Path

import trimesh
from build_button_colliders import sampled_distances


def checked_mesh(root, record):
    path = root / record["file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"Mesh hash mismatch: {path}")
    return trimesh.load(str(path), force="mesh", process=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("visual_dir", type=Path)
    parser.add_argument("candidate_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    inventory = json.loads((args.visual_dir / "inventory.json").read_text())
    candidates = json.loads((args.candidate_dir / "collision_audit.json").read_text())
    records = {r["name"]: r for r in inventory["objects"]}
    results = []
    for candidate in candidates["candidates"]:
        letter = candidate["source_object"][0]
        names = [
            letter,
            letter + "-Button",
            letter + "-Interior",
            letter + "-Interior2",
        ]
        layers = [checked_mesh(args.visual_dir, records[name]) for name in names]
        hull = checked_mesh(args.candidate_dir, candidate)
        combined = trimesh.util.concatenate(layers)
        results.append(
            {
                "button": letter,
                "visual_group": [
                    {"name": name, "sha256": records[name]["sha256"]} for name in names
                ],
                "candidate_sha256": candidate["sha256"],
                "candidate_to_outer": sampled_distances(hull, layers[1]),
                "candidate_to_all_layers": sampled_distances(hull, combined),
                "all_layers_to_candidate": sampled_distances(combined, hull),
                "mechanical_group_approved": False,
                "collision_approved": False,
            }
        )
    result = {
        "method": "All vertices and face centroids, closest point on triangles; not exact Hausdorff",
        "source_sha256": inventory["source_sha256"],
        "trimesh_version": trimesh.__version__,
        "grouping_evidence": "Verified Blender object labels; mechanical correspondence unresolved",
        "meters_per_native_unit": None,
        "physical_acceptance_threshold": None,
        "buttons": results,
    }
    with args.output.open("x") as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write("\n")


if __name__ == "__main__":
    main()
