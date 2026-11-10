"""Independent geometry check for contact filtering against the fixed root.

No dynamics or collision settings are changed. Distances use actual cooked
shell triangles, not SDF contact callbacks. Negative gap means the prescribed
sphere overlaps the shell surface, even if PhysX reports no contact pair.
"""
import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import sapien
import trimesh

from tests.acceptance import load_suite
from tests.acceptance.robotwin import executor
from tests.acceptance.robotwin.run_suite import cpu_scene


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--resources', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES'] = str(a.resources)
    sapien.physx.set_scene_config(cpu_workers=0, enable_tgs=True)
    suite = load_suite()
    case = suite.case('View')
    e = executor.RobotwinPressExecutor()
    with patch.object(executor, 'create_scene', side_effect=cpu_scene):
        e.setup([*case.root_pose.position_m, *case.root_pose.orientation_wxyz], .004)
    body = e.links['controller_body']
    meshes = []
    shapes = []
    for shape in body.get_collision_shapes():
        transform = (body.entity_pose*shape.local_pose).to_transformation_matrix()
        vertices = np.asarray(shape.get_vertices(), dtype=float)*shape.get_scale()
        vertices = vertices@transform[:3, :3].T+transform[:3, 3]
        faces = np.asarray(shape.get_triangles()).reshape(-1, 3)
        meshes.append(trimesh.Trimesh(vertices=vertices, faces=faces, process=False))
        shapes.append(dict(type=type(shape).__name__, vertices=len(vertices), triangles=len(faces),
            collision_groups=list(shape.get_collision_groups()), contact_offset_m=shape.get_contact_offset()))
    result = dict(method='minimum Euclidean sphere-center distance to cooked shell triangles minus radius; negative indicates surface overlap, not an SDF depth',
        sample_method='129 uniform points including both endpoints on the exact prescribed press line; hold endpoint exact',
        shell=body.name, shell_shapes=shapes, root_pose=[float(x) for x in (*e.art.get_root_pose().p, *e.art.get_root_pose().q)], cases={})
    for registration in sorted(a.run.glob('*/registration.json')):
        r = json.loads(registration.read_text())
        start, end = np.asarray(r['plan']['start_m']), np.asarray(r['plan']['end_m'])
        points = start+(end-start)*np.linspace(0, 1, 129)[:, None]
        distances = np.full(len(points), np.inf)
        for mesh in meshes:
            # Work in short batches to bound naive point/triangle memory.
            for first in range(0, len(points), 4):
                _, distance, _ = trimesh.proximity.closest_point_naive(mesh, points[first:first+4])
                distances[first:first+4] = np.minimum(distances[first:first+4], distance)
        gap = distances-r['radius_m']
        bound = float(np.linalg.norm(end-start)/256)
        landmarks = start+np.asarray(r['plan']['direction'])*np.asarray([
            .005, .005+.95*r['plan']['full_travel_m'], .005+r['plan']['full_travel_m']])[:, None]
        landmark_distances = np.full(3, np.inf)
        for mesh in meshes:
            _, d, _ = trimesh.proximity.closest_point_naive(mesh, landmarks)
            landmark_distances = np.minimum(landmark_distances, d)
        result['cases'][registration.parent.name] = dict(hold_surface_gap_m=float(gap[-1]),
            minimum_sampled_surface_gap_m=float(gap.min()),
            continuous_gap_lower_bound_m=float(gap.min()-bound), lipschitz_error_bound_m=bound,
            gap_at_cap_touch_95pct_full_m=(landmark_distances-r['radius_m']).tolist(),
            sum_probe_shell_contact_offsets_m=.0002+max(s['contact_offset_m'] for s in shapes),
            overlapping_sample_count=int(sum(gap < 0)), total_samples=len(gap),
            stroke_fraction_at_minimum=float(np.argmin(gap)/(len(gap)-1)))
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
