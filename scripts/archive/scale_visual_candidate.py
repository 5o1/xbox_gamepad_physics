"""Create a width-matched visual proxy, never a calibrated mechanical model."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def parse_vertices(lines):
    return [
        tuple(map(float, line.split()[1:])) for line in lines if line.startswith("v ")
    ]


def width_scale(vertices, target_width):
    if not vertices or not math.isfinite(target_width) or target_width <= 0:
        raise ValueError("Missing vertices or invalid target width")
    if any(len(p) != 3 or not all(math.isfinite(x) for x in p) for p in vertices):
        raise ValueError("Invalid vertex")
    width = max(p[0] for p in vertices) - min(p[0] for p in vertices)
    if width <= 0:
        raise ValueError("Zero width")
    return target_width / width


def scale_lines(lines, scale):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid scale")
    return [
        "v " + " ".join(format(float(v) * scale, ".17g") for v in line.split()[1:])
        if line.startswith("v ")
        else line
        for line in lines
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("visual_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    evidence_path = root / "references/1708_dimensions.json"
    evidence = json.loads(evidence_path.read_text())
    inventory_path = args.visual_dir / "inventory.json"
    inventory = json.loads(inventory_path.read_text())
    excluded = evidence["scaling_candidate"]["excluded_objects"]
    records, all_vertices = [], []
    for record in inventory["objects"]:
        if record["name"] in excluded:
            continue
        path = args.visual_dir / record["file"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError(f"Source hash mismatch: {path}")
        lines = raw.decode().splitlines()
        vertices = parse_vertices(lines)
        all_vertices.extend(vertices)
        records.append((record, lines, vertices))
    scale = width_scale(all_vertices, evidence["dimensions_m"]["width"])
    args.output.mkdir(parents=True, exist_ok=False)
    outputs, delivered_vertices = [], []
    for record, lines, original in records:
        path = args.output / record["file"]
        path.write_text("\n".join(scale_lines(lines, scale)) + "\n")
        delivered_lines = path.read_text().splitlines()
        delivered = parse_vertices(delivered_lines)
        if len(delivered) != len(original):
            raise ValueError("Vertex count changed")
        if [s for s in lines if not s.startswith("v ")] != [
            s for s in delivered_lines if not s.startswith("v ")
        ]:
            raise ValueError("Non-position data changed")
        error = max(
            abs(a - b / scale)
            for p, q in zip(original, delivered)
            for a, b in zip(p, q)
        )
        # Floating-point serialization only, not a physical acceptance tolerance.
        tolerance = 32 * math.ulp(max(1.0, max(abs(x) for p in original for x in p)))
        if error > tolerance:
            raise ValueError("Coordinate roundtrip failed")
        delivered_vertices.extend(delivered)
        outputs.append(
            {
                "name": record["name"],
                "file": path.name,
                "source_sha256": record["sha256"],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "roundtrip_error_native": error,
                "collision_approved": False,
            }
        )
    actual_width = max(p[0] for p in delivered_vertices) - min(
        p[0] for p in delivered_vertices
    )
    if not math.isclose(actual_width, evidence["dimensions_m"]["width"], rel_tol=1e-14):
        raise ValueError("Width check failed")
    report = {
        "status": "width_matched_visual_proxy_not_1708_mechanical_asset",
        "meters_per_native_unit": scale,
        "width_m": actual_width,
        "excluded_objects": excluded,
        "objects": outputs,
        "source_shape_preserved": True,
        "mechanical_revision_match": False,
        "collision_approved": False,
        "dynamics_ready": False,
        "limitation": "Width fit does not identify pivots or local dimensions; source shape/revision mismatch remains. No shell holes repaired.",
    }
    (args.output / "inventory.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "objects"}, indent=2))


if __name__ == "__main__":
    main()
