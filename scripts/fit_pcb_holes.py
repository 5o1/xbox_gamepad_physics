"""Fit explicit planar correspondences; retain independent holdout errors."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def fit(data):
    a = np.float64([p['scan'] for p in data['fit']])
    b = np.float64([p['photo'] for p in data['fit']])
    if len(a) < 4 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Need four finite correspondences')
    h, _ = cv2.findHomography(a, b, 0)
    if h is None or not np.isfinite(h).all() or abs(np.linalg.det(h)) < 1e-12:
        raise ValueError('Degenerate correspondence geometry')
    inv = np.linalg.inv(h)
    results = []
    for p in data['holdout']:
        projected = cv2.perspectiveTransform(np.float64([[p['scan']]]), h)[0,0]
        back = cv2.perspectiveTransform(np.float64([[p['photo']]]), inv)[0,0]
        results.append(dict(name=p['name'], predicted_photo_px=projected.tolist(),
                            observed_photo_px=p['photo'],
                            photo_error_px=float(np.linalg.norm(projected-p['photo'])),
                            scan_error_px=float(np.linalg.norm(back-p['scan']))))
    return {'status':'planar_fit_not_metric_calibration', 'homography':h.tolist(),
            'holdouts':results, 'physical_calibration_approved':False,
            'metric_scale':None, 'joint_pivots':None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('landmarks', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raw = args.landmarks.read_bytes()
    result = fit(json.loads(raw))
    result.update(landmarks_sha256=hashlib.sha256(raw).hexdigest(), opencv=cv2.__version__)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result))
