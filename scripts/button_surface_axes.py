"""Triangle-area PCA of visual button layers, not mechanical axis calibration.

Method: CGAL Principal Component Analysis manual (triangle surface weighting).
Uniform triangle barycentric moments give E[li^2]=1/6, E[li*lj]=1/12.
Thus E[xx^T]=(sum(vi vi^T)+s s^T)/12, s=sum(vi).
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def surface_axes(triangles):
    t = np.asarray(triangles, dtype=float)
    if t.ndim != 3 or t.shape[1:] != (3, 3) or not len(t) or not np.isfinite(t).all():
        raise ValueError('Expected finite triangles [N,3,3]')
    origin = t[0, 0].copy()
    t = t-origin
    areas = np.linalg.norm(np.cross(t[:,1]-t[:,0], t[:,2]-t[:,0]), axis=1)/2
    area = areas.sum()
    if not np.isfinite(area) or area <= 0:
        raise ValueError('No nondegenerate triangle surface')
    weights = areas/area
    center = np.einsum('n,ni->i', weights, t.mean(axis=1))
    # Recenter before forming second moments, avoiding global-coordinate cancellation.
    v = t-center
    s = v.sum(axis=1)
    second = (np.einsum('nki,nkj->nij', v, v)+np.einsum('ni,nj->nij', s, s))/12
    covariance = np.einsum('n,nij->ij', weights, second)
    values, vectors = np.linalg.eigh(covariance)
    return {'area':float(area), 'surface_centroid':(center+origin).tolist(),
            'covariance':covariance.tolist(), 'eigenvalues_ascending':values.tolist(),
            'principal_directions':vectors.T.tolist(),
            'axis_sign_determined':False, 'mechanical_axis':None}


def inspect(root):
    import trimesh
    inventory = json.loads((root/'inventory.json').read_text())
    records = {r['name']:r for r in inventory['objects']}
    result = {}
    for letter in 'ABXY':
        layers = {}
        for name in (letter, letter+'-Button', letter+'-Interior', letter+'-Interior2'):
            r = records[name]
            path = root/r['file']
            if hashlib.sha256(path.read_bytes()).hexdigest() != r['sha256']:
                raise ValueError(f'Hash mismatch: {name}')
            mesh = trimesh.load(str(path), force='mesh', process=False)
            layers[name] = {'sha256':r['sha256'], **surface_axes(mesh.triangles)}
        # Compare the minimum-variance surface normals only as a diagnostic.
        base = np.array(layers[letter+'-Button']['principal_directions'][0])
        for layer in layers.values():
            dot = abs(np.dot(base, layer['principal_directions'][0]))
            layer['min_axis_angle_to_outer_deg'] = float(np.degrees(np.arccos(np.clip(dot,0,1))))
        result[letter] = layers
    return {'method':'exact uniform triangle-surface covariance, eigendecomposition',
            'length_unit':'width-proxy metre, not calibrated 1708 geometry',
            'physical_axis_adopted':False, 'buttons':result}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('visual_dir', type=Path)
    args = p.parse_args()
    print(json.dumps(inspect(args.visual_dir), indent=2, allow_nan=False))
