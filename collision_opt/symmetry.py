"""Project hull surfaces to source regions; classify against the x=0 mirror.

Exact requires an actual mirrored triangle with all three vertex matches.
Approximate/asymmetric use source-face-centroid mirror distance to the whole
neutral source assembly, matching the historical whole-assembly target scope.
Mixed region fractions are retained; a dominant label is only a summary.
"""
import numpy as np
from scipy.spatial import cKDTree

from .distance import TriangleDistance
from .metrics import sample


def source_regions(sources, settings):
    triangles = np.concatenate([mesh.triangles for mesh in sources.values()])
    target = TriangleDistance(triangles)
    tree = cKDTree(triangles.mean(axis=1))
    mirror = triangles.copy()
    mirror[:, :, 0] *= -1
    candidate_ids = tree.query(mirror.mean(axis=1), k=min(8, len(triangles)))[1]
    if candidate_ids.ndim == 1:
        candidate_ids = candidate_ids[:, None]
    exact = np.zeros(len(mirror), dtype=bool)
    for i, (tri, ids) in enumerate(zip(mirror, candidate_ids)):
        differences = np.linalg.norm(tri[None, :, None, :] - triangles[ids, None, :, :], axis=-1)
        # Bidirectional corner matches imply a triangle with matching geometry,
        # independent of winding/permutation. No nearest-vertex-only claim.
        match = np.maximum(differences.min(axis=2).max(axis=1),
                           differences.min(axis=1).max(axis=1))
        exact[i] = match.min() < settings['exact_threshold_mm']/1000
    residual = target.query(mirror.mean(axis=1))[0]*1000
    region = np.where(exact, 0, np.where(residual < settings['approximate_threshold_mm'], 1, 2))
    result, offset = {}, 0
    for name, mesh in sources.items():
        result[name] = dict(region=region[offset:offset+len(mesh.faces)],
                            residual_mm=residual[offset:offset+len(mesh.faces)])
        offset += len(mesh.faces)
    return result


def classify(hulls, sources, settings):
    regions = source_regions(sources, settings)
    trees = {name: TriangleDistance(mesh.triangles) for name, mesh in sources.items()}
    labels = ['exact', 'approximate', 'asymmetric']
    rows = []
    for record in hulls:
        name, mesh = record['component'], record['mesh']
        points = sample(mesh, settings['seed']+record['hull_index'],
                        settings['density_points_per_mm2'])
        _, nearest, _ = trees[name].query(points, return_indices=True)
        per_face=np.maximum(1,np.ceil(mesh.area_faces*settings['density_points_per_mm2']*1e6).astype(int))
        weights=np.repeat(mesh.area_faces/per_face,per_face)
        counts = np.bincount(regions[name]['region'][nearest],weights=weights,minlength=3)
        fractions = counts / counts.sum()
        rows.append({k: record[k] for k in ('component','hull_index','shape_index','link')} |
                    dict(symmetry_region=labels[int(fractions.argmax())],
                         symmetry_fractions=dict(zip(labels, fractions.tolist())),
                         symmetry_source_faces=int(len(np.unique(nearest))),
                         source_projected_samples=len(points),
                         max_source_centroid_mirror_residual_mm=float(
                             regions[name]['residual_mm'][nearest].max())))
    return rows
