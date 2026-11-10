"""K diagnostic only: native kinematic spheres, never a replacement for T4.

Run with the existing a3 environment and immutable full_controls resources.
All joint forces, drives, materials and signals retain the upstream definitions.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import time
from unittest.mock import patch

import numpy as np
import sapien

from experiments.robotwin.station_rtf.overrides import policy
from tests.acceptance import load_suite
from tests.acceptance.robotwin import executor
from tests.acceptance.robotwin.probe import contact_plan, cooked_vertices
from tests.acceptance.robotwin.run_suite import cpu_scene
from tests.acceptance.scoring import misfires, score_case, target_value

DIGITAL = ['A', 'B', 'X', 'Y', 'View', 'Menu', 'Guide', 'LB', 'RB',
           'Dpad_up', 'Dpad_down', 'Dpad_left', 'Dpad_right', 'L3', 'R3', 'Pair']


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def actual_surface(link, center, outward):
    """Intersect the center ray with actual cooked triangles, not their convex hull."""
    hits = []
    for si, shape in enumerate(link.get_collision_shapes()):
        transform = (link.entity_pose*shape.local_pose).to_transformation_matrix()
        vertices = np.asarray(shape.get_vertices(), dtype=float)*shape.get_scale()
        vertices = vertices@transform[:3, :3].T+transform[:3, 3]
        faces = np.asarray(shape.get_triangles()).reshape(-1, 3)
        for ti, triangle in enumerate(vertices[faces]):
            a, b, c = triangle
            matrix = np.column_stack((b-a, c-a, -outward))
            if abs(np.linalg.det(matrix)) < 1e-15:
                continue
            u, v, distance = np.linalg.solve(matrix, center-a)
            if u >= -1e-8 and v >= -1e-8 and u+v <= 1+1e-8:
                hits.append((float(distance), si, ti, float(u), float(v), triangle))
    if not hits:
        raise ValueError('Center ray misses actual collision triangles')
    distance, si, ti, u, v, triangle = max(hits, key=lambda hit: hit[0])
    return center+distance*outward, dict(shape_index=si, triangle_index=ti,
        barycentric_uv=[u, v], triangle_world_m=triangle.tolist(),
        ray_origin_world_m=center.tolist(), ray_outward_world=outward.tolist())


def plan_for(e, case, radius, suite):
    # Reuse the upstream axis/sign and Dpad 8 mm moment arm definition.
    plan = contact_plan(e.gamepad, case.case_id, {**suite.settings, 'radius_m': radius})
    link, joint = e.links[plan['link']], e.joints[plan['joint']]
    vertices = np.concatenate(cooked_vertices(link))
    center = (vertices.min(0)+vertices.max(0))/2
    axis = np.asarray(plan['axis_world'], dtype=float)
    axis /= np.linalg.norm(axis)
    pivot = np.asarray(plan['pivot_m'], dtype=float)
    direction = np.asarray(plan['direction'], dtype=float)
    direction /= np.linalg.norm(direction)
    if plan['kind'] == 'dpad':
        arm = np.cross(direction, axis)
        arm /= np.linalg.norm(arm)
        center[:2] = (pivot+plan['sign']*.008*arm)[:2]
    point, registration = actual_surface(link, center, -direction)
    lo, hi = [float(x) for x in joint.get_limits()[0]]
    q0 = e.gamepad.joint_positions()[joint.name]
    # Pair preserves the historical outward/back-face approach; its positive
    # joint axis opposes that approach. Do not silently repair the known failure.
    qend = lo if plan['kind'] == 'dpad' and plan['sign'] < 0 else hi
    if plan['kind'] == 'dpad':
        angle = qend-q0
        r = point-pivot
        rotated = r*math.cos(angle)+np.cross(axis, r)*math.sin(angle)+axis*(axis@r)*(1-math.cos(angle))
        travel = float((rotated-r)@direction)
        method = 'Rodrigues rotation of selected collision point; projected on press axis'
    else:
        travel = abs(qend-q0)
        method = 'native prismatic joint limit span from neutral (m)'
    if travel <= 0:
        raise ValueError(f'Non-positive travel for {case.case_id}')
    start = point-direction*(radius+.005)
    end = start+direction*(.005+travel+.0003)
    plan.update(point_m=point.tolist(), start_m=start.tolist(), end_m=end.tolist(),
        direction=direction.tolist(), axis_world=axis.tolist(), q_neutral=q0,
        q_target_limit=qend, full_travel_m=travel, travel_method=method,
        collision_aabb_world_m=[vertices.min(0).tolist(), vertices.max(0).tolist()],
        registration=registration, point_method='upstream joint frame/AABB/8mm Dpad arm, actual outermost cooked triangle ray',
        pair_axis_conflict=case.case_id == 'Pair')
    return plan


def run_case(out, suite, original, iterations, radius, dt):
    started = time.monotonic()
    e = executor.RobotwinPressExecutor()
    with policy(iterations), patch.object(executor, 'create_scene', side_effect=cpu_scene):
        e.setup([*original.root_pose.position_m, *original.root_pose.orientation_wxyz], dt)
    # Settle normally without a probe or any change to gamepad state.
    for _ in range(round(.5/dt)):
        e.scene.step()
    plan = plan_for(e, original, radius, suite)
    limits = {j.name: j.get_limits()[0].tolist() for j in e.art.get_active_joints()}
    case = replace(original, plan=plan, joint_limits=limits)
    e.case = case
    b = e.scene.create_actor_builder()
    material = suite.fixture['sphere_material']
    b.add_sphere_collision(radius=radius, material=e.scene.create_physical_material(
        material['static_friction'], material['dynamic_friction'], material['restitution']))
    mass = suite.settings['mass_kg']
    b.set_mass_and_inertia(mass, sapien.Pose(), [2*mass*radius**2/5]*3)
    b.set_initial_pose(sapien.Pose(plan['start_m']))
    entity = b.build_kinematic(name='test_ball')
    e.ball = entity.find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)
    if not e.ball.kinematic or not hasattr(e.ball, 'set_kinematic_target'):
        raise RuntimeError('Required native kinematic API unavailable')
    for shape in e.ball.get_collision_shapes():
        mapping = suite.fixture['sapien_mapping']
        shape.set_collision_groups(mapping['collision_groups'])
        shape.set_contact_offset(mapping['contact_offset_m'])
        shape.set_rest_offset(mapping['rest_offset_m'])
    # The controller uses the requested iteration override. Probe uses the same
    # counts to avoid raising a contact island's maximum via another actor.
    e.ball.set_solver_position_iterations(iterations[0])
    e.ball.set_solver_velocity_iterations(iterations[1])
    start, end = np.asarray(plan['start_m']), np.asarray(plan['end_m'])
    distance = float(np.linalg.norm(end-start))
    count = math.ceil(distance/(suite.settings['speed_m_s']*dt))
    out.mkdir(parents=True, exist_ok=False)
    receipt = dict(plan=plan, radius_m=radius, dt_s=dt, approach_clearance_m=.005,
        speed_m_s=.005, extra_travel_m=.0003, hold_s=.5, observe_s=.5,
        art_iterations=[e.art.get_solver_position_iterations(), e.art.get_solver_velocity_iterations()],
        probe_iterations=[e.ball.get_solver_position_iterations(), e.ball.get_solver_velocity_iterations()],
        kinematic=bool(e.ball.kinematic), requested_mass_kg=mass, mass_kg=float(e.ball.mass),
        inertia_kg_m2=e.ball.inertia.tolist(),
        physical_note='kinematic target has no force cap; mass does not set its motion',
        gravity=e.scene.physx_system.config.gravity.tolist(), enable_tgs=e.scene.physx_system.config.enable_tgs,
        cpu_workers_configured=0, sleep_threshold=e.art.get_sleep_threshold(),
        native_joint_limits=limits, neutral_joints=e.gamepad.joint_positions(),
        phases=dict(press=count, hold=round(.5/dt), withdraw=count, observe=round(.5/dt)))
    save(out/'registration.json', receipt)
    rows = []
    with gzip.open(out/'trace.jsonl.gz', 'wt') as sink:
        for phase, steps in receipt['phases'].items():
            for i in range(steps):
                moved = min(distance, (i+1)*dt*.005)
                target = (start+(end-start)*(moved/distance) if phase == 'press' else
                          end if phase == 'hold' else
                          end-(end-start)*(moved/distance) if phase == 'withdraw' else start)
                e.ball.set_kinematic_target(sapien.Pose(target))
                e.scene.step()
                row = e.sample()
                row.update(step=len(rows), time_s=(len(rows)+1)*dt,
                    qvel=e.art.get_qvel().tolist(),
                    root_pose=[float(x) for x in (*e.art.get_root_pose().p, *e.art.get_root_pose().q)],
                    link_positions={n: link.entity_pose.p.tolist() for n, link in e.links.items()})
                row['probe'].update(phase=phase, phase_age_s=(i+1)*dt,
                    target_m=target.tolist(), target_tracking_error_m=float(np.linalg.norm(e.ball.pose.p-target)))
                rows.append(row)
                sink.write(json.dumps(row, allow_nan=False)+'\n')
    # Preserve the frozen scorer. Its fixed 4 ms clock requires a 4 ms sampled
    # view of the 1 ms trace. Full-resolution diagnostics below cover every row.
    stride = round(.004/dt)
    scored = []
    for phase in receipt['phases']:
        phase_rows = [r for r in rows if r['probe']['phase'] == phase]
        for r in phase_rows[stride-1::stride]:
            scored.append({**r, 'step': len(scored)})
    t4 = score_case(suite, case, scored)
    hold = [r for r in rows if r['probe']['phase'] == 'hold']
    observe = [r for r in rows if r['probe']['phase'] == 'observe']
    values = [target_value(plan, r['signals'], r['probe']['events']) for r in hold]
    bad = {}
    for r in hold:
        for n, v in misfires(plan, r['signals'], suite.criteria).items():
            bad[n] = max(bad.get(n, 0), abs(v))
    neutral = next((i for i in range(len(observe)) if all(
        abs(target_value(plan, r['signals'], r['probe']['events'])) <= suite.criteria['neutral_epsilon']
        for r in observe[i:])), None)
    return_s = neutral*dt if neutral is not None else None
    contacts = {}
    for r in rows:
        seen = set()
        for c in r['contacts']:
            name = next(n for n in c['bodies'] if n != 'test_ball')
            info = contacts.setdefault(name, dict(steps=0, phases={}, min_separation_m=None, max_force_n=0))
            phase = r['probe']['phase']
            if name not in seen:
                info['steps'] += 1
                info['phases'][phase] = info['phases'].get(phase, 0)+1
                seen.add(name)
            for p in c['points']:
                separation = p['separation_m']
                info['min_separation_m'] = separation if info['min_separation_m'] is None else min(info['min_separation_m'], separation)
                info['max_force_n'] = max(info['max_force_n'], float(np.linalg.norm(p['impulse_ns'])/dt))
    q0, qend = plan['q_neutral'], plan['q_target_limit']
    fractions = [(r['joints'][plan['joint']]-q0)/(qend-q0) for r in rows]
    internal = max(r['gamepad_internal_pairs'] for r in rows)
    result = dict(case=case.case_id, iterations=iterations, radius_mm=radius*1000, dt_ms=dt*1000,
        target_min=min(values), target_max=max(values), misfires=bad,
        return_time_after_withdraw_s=return_s, final_target=target_value(plan, observe[-1]['signals'], observe[-1]['probe']['events']),
        k_passed=min(values) >= .95 and not bad and return_s is not None and return_s <= .5 and internal == 0,
        frozen_t4_scoring=t4, max_joint_travel_fraction=max(fractions), min_joint_travel_fraction=min(fractions),
        hold_joint_fraction_range=[min((r['joints'][plan['joint']]-q0)/(qend-q0) for r in hold), max((r['joints'][plan['joint']]-q0)/(qend-q0) for r in hold)],
        contacts=contacts, non_target_contacts=[n for n in contacts if n != plan['link']],
        internal_pairs=internal, max_target_tracking_error_m=max(r['probe']['target_tracking_error_m'] for r in rows),
        max_abs_qvel=[float(x) for x in np.max(np.abs([r['qvel'] for r in rows]), axis=0)],
        joint_names=[j.name for j in e.art.get_active_joints()],
        max_root_translation_m=max(float(np.linalg.norm(np.asarray(r['root_pose'][:3])-rows[0]['root_pose'][:3])) for r in rows),
        joint_limit_excess={n: max(r.get('joint_limit_excess', {}).get(n, 0) for r in rows)
            for n in {n for r in rows for n in r.get('joint_limit_excess', {})}},
        max_cap_translation_speed_m_s=max(float(np.linalg.norm(
            np.asarray(b['link_positions'][plan['link']])-a['link_positions'][plan['link']]))/dt
            for a, b in zip(rows, rows[1:])),
        hold_samples=len(hold), observe_samples=len(observe),
        elapsed_s=time.monotonic()-started, trace_sha256=hashlib.sha256((out/'trace.jsonl.gz').read_bytes()).hexdigest())
    save(out/'result.json', result)
    print(json.dumps(result, allow_nan=False), flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resources', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cases', nargs='+', choices=DIGITAL)
    p.add_argument('--iterations', nargs=2, type=int)
    p.add_argument('--radii-mm', nargs='+', type=float, default=[4, 7])
    p.add_argument('--dt-ms', nargs='+', type=float, default=[4, 1])
    a = p.parse_args()
    os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES'] = str(a.resources.resolve())
    a.output.mkdir(parents=True, exist_ok=False)
    sapien.physx.set_scene_config(cpu_workers=0, enable_tgs=True)
    suite = load_suite()
    root = Path(__file__).resolve().parents[4]
    manifest_path = a.resources/'robotwin/full_controls/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    inputs = [Path(__file__), Path(executor.__file__), root/'tests/acceptance/data/ruling20_sdf303_v1.json',
              manifest_path, a.resources/manifest['motion_contract']]
    inputs += [a.resources/'robotwin/full_controls'/name for name in manifest['required_files']]
    inputs += [root/name for name in ['tests/acceptance/robotwin/probe.py', 'tests/acceptance/scoring.py',
        'tests/acceptance/robotwin/run_suite.py', 'experiments/robotwin/station_rtf/overrides.py']]
    # Fixed four-directory parent: probe_k -> station_rtf -> robotwin -> experiments -> checkout.
    receipt = dict(versions={n: importlib.metadata.version(n) for n in ['sapien', 'xbox-gamepad-physics']},
        python=platform.python_version(), cpu_affinity=sorted(os.sched_getaffinity(0)),
        resources=str(a.resources.resolve()), source_base='9e00dd65bf5dc0597d64b221f383ece29b082eaf',
        env={n: os.environ.get(n) for n in ['CUDA_VISIBLE_DEVICES', 'DISPLAY', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS']},
        sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
        results=[])
    save(a.output/'summary.json', receipt)
    for dt_ms in a.dt_ms:
        cases = a.cases or (DIGITAL if dt_ms == 4 else ['View', 'Menu', 'Guide'])
        for iterations in ([a.iterations] if a.iterations else [[10, 1], [64, 16]]):
            for radius_mm in a.radii_mm:
                for name in cases:
                    label = f'{iterations[0]}-{iterations[1]}_r{radius_mm:g}_dt{dt_ms:g}_{name}'
                    result = run_case(a.output/label, suite, suite.case(name), iterations, radius_mm/1000, dt_ms/1000)
                    receipt['results'].append(result)
                    save(a.output/'summary.json', receipt)


if __name__ == '__main__':
    main()
