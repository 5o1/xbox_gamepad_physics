"""Reproducible image-space layout diagnostic, explicitly not 3D metrology."""
import argparse
import hashlib
import json
from pathlib import Path


def ruler_fit(marks):
    if len(marks) < 2:
        raise ValueError('Need at least two ruler marks')
    mx = sum(x for x, _ in marks) / len(marks)
    my = sum(y for _, y in marks) / len(marks)
    denominator = sum((x - mx) ** 2 for x, _ in marks)
    if denominator == 0:
        raise ValueError('Ruler marks must span distinct distances')
    a = sum((x - mx) * (y - my) for x, y in marks) / denominator
    if a <= 0:
        raise ValueError('Expected downward increasing ruler')
    return a, my - a * mx


def analyze(data):
    a, b = ruler_fit(data['ruler_fit_mm_y_px'])
    points = data['shaft_opening_centers_px']
    dy = abs(points[1][1] - points[0][1])
    sensitivity = data['manual_readout_sensitivity_px']
    return {
        'status': 'projected_layout_diagnostic_only',
        'pixels_per_ruler_mm': a,
        'ruler_intercept_px': b,
        'held_out_residual_px': [y - (a * x + b) for x, y in data['ruler_holdout_mm_y_px']],
        'shaft_vertical_separation_px': dy,
        'ruler_plane_equivalent_separation_mm': dy / a,
        'center_readout_only_sensitivity_mm': [(dy - 2 * sensitivity) / a, (dy + 2 * sensitivity) / a],
        'warning': 'Sensitivity holds ruler fit fixed and excludes perspective, depth, lens distortion and unknown stick pose. It is not a physical-distance bound.',
        'physical_distance_m': None,
        'target_pivot_m': None,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('annotations', type=Path)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.annotations.read_text())
    if hashlib.sha256(args.image.read_bytes()).hexdigest() != data['image_sha256']:
        raise SystemExit('Image SHA256 mismatch')
    result = analyze(data)
    result['annotations_sha256'] = hashlib.sha256(args.annotations.read_bytes()).hexdigest()
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
