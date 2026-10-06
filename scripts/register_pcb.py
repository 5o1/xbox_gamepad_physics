"""Diagnostic PCB scan/photo registration, not camera or metric calibration.

Method reference: OpenCV feature matching + homography tutorial.
Use held-out correspondences selected BEFORE robust fitting; never select a
transform by test error or silently turn a fitted homography into physical axes.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def register(scan, photo):
    cv2.setRNGSeed(0)
    sift = cv2.SIFT_create()
    ks, ds = sift.detectAndCompute(scan, None)
    kp, dp = sift.detectAndCompute(photo, None)
    result = {'scan_features': len(ks), 'photo_features': len(kp),
              'physical_calibration_approved': False, 'homography': None}
    if ds is None or dp is None or len(dp) < 2:
        return dict(result, status='insufficient_descriptors')
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(ds, dp, k=2)
    good = [m for m, n in pairs if m.distance < .7 * n.distance]
    # Remove duplicate destination matches before the deterministic holdout.
    unique = {}
    for m in sorted(good, key=lambda m: m.distance):
        unique.setdefault(m.trainIdx, m)
    good = sorted(unique.values(), key=lambda m: (*ks[m.queryIdx].pt, m.trainIdx))
    result['ratio_filtered_unique_matches'] = len(good)
    if len(good) < 10:
        return dict(result, status='insufficient_correspondences')
    a = np.float32([ks[m.queryIdx].pt for m in good])
    b = np.float32([kp[m.trainIdx].pt for m in good])
    test = np.arange(len(good)) % 3 == 0
    h, mask = cv2.findHomography(a[~test], b[~test], cv2.RANSAC, 5.0)
    result.update(train_count=int((~test).sum()), holdout_count=int(test.sum()))
    if h is None or not np.isfinite(h).all():
        return dict(result, status='fit_failed')
    predicted = cv2.perspectiveTransform(a.reshape(-1, 1, 2), h).reshape(-1, 2)
    error = np.linalg.norm(predicted - b, axis=1)
    result.update(status='candidate_requires_landmark_review', homography=h.tolist(),
                  train_inliers=int(mask.sum()),
                  holdout_errors_px=error[test].tolist(),
                  holdout_median_px=float(np.median(error[test])),
                  correspondences=[{'scan_px': x.tolist(), 'photo_px': y.tolist(),
                                    'holdout': bool(t), 'error_px': float(e)}
                                   for x, y, t, e in zip(a, b, test, error)])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan', type=Path, required=True)
    parser.add_argument('--photo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mirror-scan', action='store_true', help='Explicit alternative orientation hypothesis; reported in output')
    args = parser.parse_args()
    images = [cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) for p in (args.scan, args.photo)]
    if any(image is None for image in images):
        raise SystemExit('Unreadable image')
    if args.mirror_scan:
        images[0] = cv2.flip(images[0], 1)
    result = register(*images)
    result.update(opencv_version=cv2.__version__, mirror_scan=args.mirror_scan,
                  input_sha256=[hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.scan,args.photo)],
                  method='SIFT; exact BF L2; ratio .7; unique destinations; every third x-sorted match held out; RANSAC 5 px on remaining only; seed 0',
                  warning='Thresholds are tutorial diagnostic settings, not mechanical tolerances. Feature matches may be wrong, spatially concentrated or board-revision dependent. No metric scale inferred.')
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('correspondences','homography','holdout_errors_px')}))
