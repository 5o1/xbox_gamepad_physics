"""Reference lever angular envelope, not Xbox dynamics or HID calibration.

Derivation and manufacturer evidence: references/stick_envelope.json.
All function angles are radians. Rx then Ry denotes matrix product Rx @ Ry.
No mechanical joint frames, stiffness, click axis or HID values are inferred.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
from .paths import DATA_ROOT


def finite(*values):
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Non-finite angle")


def lever_direction(qx, qy):
    finite(qx, qy)
    return (math.sin(qy), -math.sin(qx) * math.cos(qy), math.cos(qx) * math.cos(qy))


def inclination(qx, qy):
    x, y, z = lever_direction(qx, qy)
    return math.atan2(math.hypot(x, y), z)


def angular_margin(qx, qy, max_tilt):
    finite(max_tilt)
    if not 0 < max_tilt < math.pi / 2:
        raise ValueError("Expected a forward-hemisphere envelope")
    return max_tilt - inclination(qx, qy)


def boundary_coordinates(azimuth, max_tilt):
    finite(azimuth, max_tilt)
    angular_margin(0, 0, max_tilt)
    qy = math.asin(math.sin(max_tilt) * math.cos(azimuth))
    qx = math.atan2(-math.sin(max_tilt) * math.sin(azimuth), math.cos(max_tilt))
    return qx, qy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    path = DATA_ROOT / "references/stick_envelope.json"
    raw = path.read_bytes()
    source = json.loads(raw)
    limit = math.radians(source["half_sweep_max_deg"])
    samples = []
    # 360 is a diagnostic sampling choice, not a physical parameter or solver rate.
    for degree in range(360):
        qx, qy = boundary_coordinates(math.radians(degree), limit)
        samples.append(
            {
                "azimuth_deg": degree,
                "qx_rad": qx,
                "qy_rad": qy,
                "inclination_rad": inclination(qx, qy),
            }
        )
    report = {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "reference_max_tilt_rad": limit,
        "independent_axes_corner_tilt_deg": math.degrees(inclination(limit, limit)),
        "max_boundary_error_rad": max(
            abs(s["inclination_rad"] - limit) for s in samples
        ),
        "samples": samples,
        "validated": "Analytic coordinate envelope and diagnostic boundary only",
    }
    with args.output.open("x") as out:
        json.dump(report, out, indent=2, allow_nan=False)
        out.write("\n")


if __name__ == "__main__":
    main()
