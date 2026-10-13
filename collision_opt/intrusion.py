"""Exact Boolean volume and convex-hull inward penetration depth (all mm).

Depth is max_{p in H intersect P} distance(p, boundary(H)). It measures how
deeply protected points lie inside the offending hull, not a separating rigid
translation. A convex hull's inward distance is the minimum normalized face
slack. Its maximum over each intersection-boundary triangle is a linear
program. The hull Chebyshev centre covers an interior maximum; otherwise a
segment towards that centre reaches the intersection boundary without
decreasing the objective. This also handles a nonconvex/disconnected P.
"""
import numpy as np
from scipy.optimize import linprog
from scipy.spatial import ConvexHull

from .baseline_control import solid, mesh_of
from .metrics import winding


def _checked(result):
    import manifold3d
    if result.status() != manifold3d.Error.NoError:
        raise ValueError(f'Boolean error: {result.status()}')
    return result


def maximum_depth(hull, intersection_mesh, lp_tolerance_mm=1e-7):
    """Return numerical maximum and witness; input coordinates are mm."""
    eq = ConvexHull(hull.vertices).equations
    # Qhull normals are normalized; deduplicate coplanar planes for smaller LPs.
    _, indices = np.unique(np.round(eq, 12), axis=0, return_index=True)
    eq = eq[indices]
    options = {'primal_feasibility_tolerance': max(1e-10, lp_tolerance_mm),
               'dual_feasibility_tolerance': max(1e-10, lp_tolerance_mm)}
    centre = linprog([0., 0., 0., -1.],
        A_ub=np.column_stack((eq[:, :3], np.ones(len(eq)))), b_ub=-eq[:, 3],
        bounds=[(None, None)]*3 + [(0., None)], method='highs', options=options)
    if not centre.success:
        raise ValueError(f'Chebyshev centre LP failed: {centre.message}')
    if winding(centre.x[None, :3], intersection_mesh.triangles)[0] > .5:
        return dict(max_depth_mm=float(centre.x[3]), witness_mm=centre.x[:3].tolist(),
                    depth_method='convex inward face-slack LP', boundary_lps=0)
    points = intersection_mesh.vertices
    slack = -(points @ eq[:, :3].T + eq[:, 3])
    depths = slack.min(axis=1)
    best = max(0., float(depths.max()))
    witness = points[int(np.argmax(depths))]
    triangles = intersection_mesh.faces
    # min_j max_corner slack_j bounds every point in a triangle.
    upper = slack[triangles].max(axis=1).min(axis=1)
    solved = 0
    for index in np.argsort(upper)[::-1]:
        if upper[index] <= best + lp_tolerance_mm:
            break
        ids = triangles[index]
        result = linprog([0., 0., 0., -1.],
            A_ub=np.column_stack((-slack[ids].T, np.ones(len(eq)))),
            b_ub=np.zeros(len(eq)), A_eq=[[1., 1., 1., 0.]], b_eq=[1.],
            bounds=[(0., 1.)]*3 + [(0., None)], method='highs', options=options)
        if not result.success:
            raise ValueError(f'Boundary depth LP failed: {result.message}')
        solved += 1
        if result.x[3] > best:
            best = float(result.x[3])
            witness = result.x[:3] @ points[ids]
    return dict(max_depth_mm=best, witness_mm=witness.tolist(),
                depth_method='convex inward face-slack LP', boundary_lps=solved)


def check_pair(hull_mm, protection_mm, tolerance_mm=.01,
               minimum_volume_mm3=1e-6, lp_tolerance_mm=1e-7,
               protection_solid=None):
    """Check one H/P pair; never modifies either input mesh."""
    zero = dict(volume_mm3=0., max_depth_mm=0., witness_mm=None,
                intrudes=False, numerical_sliver=False, boundary_lps=0)
    if not len(protection_mm.faces):
        return zero
    if np.any(hull_mm.bounds[1] < protection_mm.bounds[0]) or np.any(
            protection_mm.bounds[1] < hull_mm.bounds[0]):
        return zero
    p = solid(protection_mm) if protection_solid is None else protection_solid
    intersection = _checked(solid(hull_mm) ^ p)
    volume = max(0., float(intersection.volume()))
    if intersection.is_empty() or volume <= minimum_volume_mm3:
        return dict(zero, volume_mm3=volume, numerical_sliver=volume > 0)
    depth = maximum_depth(hull_mm, mesh_of(intersection), lp_tolerance_mm)
    intrudes = depth['max_depth_mm'] > tolerance_mm + lp_tolerance_mm
    return dict(depth, volume_mm3=volume, intrudes=intrudes,
                numerical_sliver=not intrudes)


def inspect_body(hulls, spaces, cfg):
    """All body hulls versus all protected spaces; hull records have mesh in m."""
    settings = cfg['intrusion']
    tolerance = cfg['protection']['numerical_tolerance_mm']
    all_spaces=spaces
    spaces={name:mesh for name,mesh in all_spaces.items()
            if name.split(':')[-1] in ('approach','sweep','cap_gap','combined')}
    solids = {name: solid(mesh) for name, mesh in spaces.items() if len(mesh.faces)}
    records = []
    for record in hulls:
        if record['link'] != 'controller_body':
            continue
        mesh = record['mesh'].copy()
        mesh.vertices *= 1000
        for name, space in spaces.items():
            result = check_pair(mesh, space, tolerance,
                settings['minimum_volume_mm3'], settings['lp_tolerance_mm'],
                solids.get(name))
            lower=all_spaces.get(name+'_sampled')
            if lower is not None and result['intrudes']:
                sampled=check_pair(mesh,lower,tolerance,settings['minimum_volume_mm3'],
                                   settings['lp_tolerance_mm'])
                result.update(sampled_sweep_volume_mm3=sampled['volume_mm3'],
                    sampled_sweep_max_depth_mm=sampled['max_depth_mm'],
                    confirmed_on_sampled_sweep=sampled['intrudes'])
            records.append({k: record[k] for k in ('component', 'hull_index', 'shape_index', 'link')}
                           | dict(space=name, **result))
        print(f"intrusion: {record['component']} {record['hull_index']} checked", flush=True)
    return records
