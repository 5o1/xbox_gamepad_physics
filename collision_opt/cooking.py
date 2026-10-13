"""Run only the PhysX cooking inspection on the prescribed SAPIEN node.

Inputs are the existing link-local multi-object OBJ files. load_multiple is
the exact SAPIEN 3.0.3 builder path for existing multiple_convex_meshes records.
No simulation, rendering, hardware, or asset rewriting takes place.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import ConvexHull
from scipy.optimize import linear_sum_assignment

from .io import load_hulls
from .distance import TriangleDistance
from .metrics import sample, stats_mm


def compare(original, cooked, density=4, seed=20261013):
    """Bidirectional surface samples plus vertices; lengths returned in mm."""
    forward = np.concatenate((original.vertices, sample(original, seed, density)))
    backward = np.concatenate((cooked.vertices, sample(cooked, seed+1, density)))
    a = TriangleDistance(cooked.triangles).query(forward)[0]*1000
    b = TriangleDistance(original.triangles).query(backward)[0]*1000
    # For convex solids, max distance-to-SOLID is attained at a source vertex.
    # Unsigned vertex-to-boundary distance bounds that solid distance, so the
    # larger of the two vertex maxima is a conservative solid Hausdorff bound.
    return dict(input_to_cooked_surface=stats_mm(a),
                cooked_to_input_surface=stats_mm(b),
                max_surface_error_sample_mm=float(max(a.max(), b.max())),
                convex_solid_hausdorff_upper_bound_mm=float(max(
                    a[:len(original.vertices)].max(), b[:len(cooked.vertices)].max())),
                vertices_included=True, density_points_per_mm2=density)


def run(hull_directory, output, density=4, seed=20261013):
    import sapien
    if sapien.__version__ != '3.0.3':
        raise RuntimeError(f'Requires SAPIEN 3.0.3, got {sapien.__version__}')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    identity_inputs=output/'identity_inputs'
    identity_inputs.mkdir(exist_ok=True)
    material = sapien.physx.PhysxMaterial(.5, .5, 0.)
    rows, arrays = [], {}
    body_offset = 0
    files = sorted(Path(hull_directory).glob('*.obj'),
                   key=lambda p: (p.stem not in ('shell', 'shell_front_plate'),
                                  p.stem == 'shell_front_plate', p.stem))
    for path in files:
        originals = load_hulls(path)
        shapes = sapien.physx.PhysxCollisionShapeConvexMesh.load_multiple(
            str(path), [1., 1., 1.], material)
        if len(shapes) != len(originals):
            raise RuntimeError(f'{path.stem}: dropped/reordered shape count')
        # Assimp/load_multiple may reorder OBJ objects. Recover identity by the
        # native cooked geometry of each input, not by assuming object order.
        independent_vertices=[]
        shape_vertices=[np.asarray(s.get_vertices(),dtype=float)*s.get_scale() for s in shapes]
        for i, (_, mesh) in enumerate(originals):
            # The vertex-array constructor uses a different input ordering and
            # may cook differently. Use the SAME file-import path as the real
            # loader, with an unchanged isolated object's faces and coordinates.
            independent_path=identity_inputs/f'{path.stem}_{i}.obj'
            mesh.export(independent_path,digits=17)
            independent_shapes=sapien.physx.PhysxCollisionShapeConvexMesh.load_multiple(
                str(independent_path),[1.,1.,1.],material)
            if len(independent_shapes)!=1:
                raise RuntimeError(f'{path.stem}/{i}: isolated object count changed')
            independent=independent_shapes[0]
            independent_vertices.append(np.asarray(independent.get_vertices(),dtype=float))
        equations=[ConvexHull(v).equations for v in shape_vertices]
        independent_equations=[ConvexHull(v).equations for v in independent_vertices]
        # Redundant/copanar cooked vertices may differ while the solid is the
        # same. Mutual normalized face violations test solid identity.
        distances=np.array([[max(0.,float((iv@eq[:,:3].T+eq[:,3]).max()),
                                  float((v@ieq[:,:3].T+ieq[:,3]).max()))
                             for v,eq in zip(shape_vertices,equations)]
                            for iv,ieq in zip(independent_vertices,independent_equations)])
        original_ids, shape_ids=linear_sum_assignment(distances)
        mapping=dict(zip(original_ids.tolist(),shape_ids.tolist()))
        if distances[original_ids,shape_ids].max()>1e-7:
            raise RuntimeError(f'{path.stem}: cannot identify cooked OBJ objects')
        for i, (name, mesh) in enumerate(originals):
            actual_index=mapping[i]
            shape=shapes[actual_index]
            v = np.asarray(shape.get_vertices(), dtype=float)*shape.get_scale()
            faces = np.asarray(shape.get_triangles(), dtype=int).reshape(-1, 3)
            cooked = trimesh.Trimesh(v, faces, process=False)
            # Compare to the independently imported single-object file.
            identity=float(distances[i,actual_index])
            if identity > 1e-7:
                raise RuntimeError(f'{path.stem}/{i}: multi-object order not verified ({identity} m)')
            link = 'controller_body' if path.stem in ('shell', 'shell_front_plate') else path.stem
            row = dict(component=path.stem, hull_index=i, hull_name=name, link=link,
                       shape_index=body_offset+actual_index if link == 'controller_body' else actual_index,
                       input_vertices=len(mesh.vertices), cooked_vertices=len(v),
                       input_faces=len(mesh.faces), cooked_faces=len(faces),
                       shape_order_check_max_mm=float(identity*1000),
                       **compare(mesh, cooked, density, seed+i))
            rows.append(row)
            arrays[f'{path.stem}_v{i}'] = v
            arrays[f'{path.stem}_f{i}'] = faces
        if path.stem in ('shell', 'shell_front_plate'):
            body_offset += len(shapes)
        print(f'cooked {path.stem}: {len(shapes)}', flush=True)
    np.savez_compressed(output/'cooked_meshes.npz', **arrays)
    result = dict(schema_version=1, sapien=sapien.__version__, python=sys.executable,
                  source_directory=str(hull_directory), hulls=rows,
                  method='SAPIEN native load_multiple on existing link-local OBJ; independently verify shape order',
                  units=dict(length='mm', source_coordinates='link-local m'),
                  config=dict(density_points_per_mm2=density, seed=seed),
                  vertex_limit=255, count=len(rows))
    (output/'cooking.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hulls', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--density', type=float, default=4)
    parser.add_argument('--seed', type=int, default=20261013)
    args = parser.parse_args()
    run(args.hulls, args.output, args.density, args.seed)
