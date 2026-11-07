"""Native MuJoCo implementation of frozen stick_click_threshold_20261105_v1.

Only fixture loads are updated while stepping: gamepad coordinates, click
controls and signal mapping are never changed by an experimental load.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path

import mujoco as mj
import numpy as np

from tests.acceptance import load_suite
from tests.acceptance.records import ResultSink
from xbox_gamepad_physics.mujoco.builder import CONTACT_NUMERICS
from xbox_gamepad_physics.mujoco.loader import make_spec, load_standalone
from xbox_gamepad_physics.mujoco.numerics import apply_standalone_policy

PROTOCOL_PATH = Path(__file__).with_name('stick_click_protocol.json')
P = json.loads(PROTOCOL_PATH.read_text())
_MODEL_CACHE = {}


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


class Fixture:
    def __init__(self, resource_root, side, angle=0, *, hold=True, probe=False):
        self.side, self.hold, self.angle = side, hold, angle
        self.suite = load_suite()
        case = self.suite.case('L3' if side == 'left' else 'R3')
        key = (str(Path(resource_root).resolve()), case.root_pose, bool(probe))
        if key in _MODEL_CACHE:
            self.asset, self.model = _MODEL_CACHE[key]
        else:
            self.asset = make_spec(resource_root=resource_root, fixed_root=True,
                                   pose=case.root_pose, attach_visual=False)
            spec = self.asset.spec
            self.policy = self.asset.numerical_policy
            apply_standalone_policy(spec.option, self.policy)
            spec.option.gravity = P['gravity_m_s2']
            spec.option.sdf_iterations = self.asset.sdf_policy['sdf_iterations']
            spec.option.sdf_initpoints = self.asset.sdf_policy['sdf_initpoints']
            self.dt = self.policy['acceptance_step_s']
            self.substeps = self.policy['substeps_per_acceptance_step']
            if probe:
                mass, radius = self.suite.settings['mass_kg'], self.suite.settings['radius_m']
                body = spec.worldbody.add_body(name='click_probe', pos=[0, 0, 2])
                body.mass, body.ipos, body.iquat = mass, [0, 0, 0], [1, 0, 0, 0]
                body.inertia = [2*mass*radius**2/5]*3
                body.explicitinertial = True
                body.add_freejoint(name='click_probe_free')
                numerics = {k: v for k, v in CONTACT_NUMERICS.items() if k not in {'solref', 'solmix'}}
                body.add_geom(name='click_probe', type=mj.mjtGeom.mjGEOM_SPHERE,
                              size=[radius, 0, 0], contype=1, conaffinity=1, **numerics)
            # Numerical fixture only: native affine position drives retain the
            # engine's implicit stiffness/damping treatment at the approved dt.
            for fixture_side in ('left', 'right'):
                for suffix in ('x', 'y'):
                    spec.add_actuator(name=f'click_fixture_{fixture_side}_{suffix}',
                        target=f'{fixture_side}_stick_{suffix}', trntype=mj.mjtTrn.mjTRN_JOINT,
                        gaintype=mj.mjtGain.mjGAIN_FIXED, biastype=mj.mjtBias.mjBIAS_AFFINE,
                        gainprm=[0]*10, biasprm=[0]*10, ctrllimited=False,
                        forcelimited=True, forcerange=[-P['T1']['tilt_fixture_effort_nm'],
                                                      P['T1']['tilt_fixture_effort_nm']])
            self.model = spec.compile()
            _MODEL_CACHE[key] = (self.asset, self.model)
        self.policy = self.asset.numerical_policy
        self.dt = self.policy['acceptance_step_s']
        self.substeps = self.policy['substeps_per_acceptance_step']
        self.data = mj.MjData(self.model)
        self.gamepad = self.asset.bind(self.model, self.data)
        for fixture_side in ('left', 'right'):
            for suffix in ('x', 'y'):
                act = self.model.actuator(f'click_fixture_{fixture_side}_{suffix}')
                active = hold and fixture_side == side
                stiffness = P['T1']['tilt_fixture_stiffness_nm_per_rad'] if active else 0.
                damping = P['T1']['tilt_fixture_damping_nms_per_rad'] if active else 0.
                act.gainprm[:] = [stiffness]+[0]*9
                act.biasprm[:] = [0, -stiffness, -damping]+[0]*7
                self.data.ctrl[act.id] = 0.
        self.cap_id = self.model.body(side+'_stick').id
        self.root_id = self.model.body('controller_body').id
        self.cap_geoms = [i for i in range(self.model.ngeom)
                          if self.model.geom_bodyid[i] == self.cap_id]
        mj.mj_forward(self.model, self.data)
        points = []
        for gid in self.cap_geoms:
            mid = self.model.geom_dataid[gid]
            start, count = self.model.mesh_vertadr[mid], self.model.mesh_vertnum[mid]
            local = self.model.mesh_vert[start:start+count]
            points.extend(local @ self.data.geom_xmat[gid].reshape(3, 3).T + self.data.geom_xpos[gid])
        points = np.asarray(points)
        center = (points.min(0)+points.max(0))/2
        self.center_local = self.data.xmat[self.cap_id].reshape(3, 3).T @ (center-self.data.xpos[self.cap_id])
        self.inward = -self.data.xmat[self.root_id].reshape(3, 3)[:, 2].copy()
        self.probe_id = self.model.body('click_probe').id if probe else None
        self.probe_geom_id = self.model.geom('click_probe').id if probe else None
        for _ in range(round(P['settle_s']/self.dt)):
            if hold:
                # Ruling 1 repair retained by ruling 2: avoid saturating the
                # tiny tilt inertia with an instantaneous 12/20 degree target.
                # The 0.2 s ramp is inside the original 1 s fixture settle.
                self.data.ctrl[self.model.actuator(f'click_fixture_{side}_x').id] = (
                    math.radians(angle) * min(1., self.data.time/.2))
            compensation = -np.asarray(P['gravity_m_s2'])*self.suite.settings['mass_kg'] if probe else None
            self.step(probe_force=compensation)

    def shaft(self):
        matrix = self.data.xmat[self.cap_id].reshape(3, 3)
        return -matrix[:, 2], matrix @ self.center_local+self.data.xpos[self.cap_id]

    def sample(self):
        inward, _ = self.shaft()
        cosine = float(np.clip(inward @ self.inward, -1., 1.))
        q = self.gamepad.joint_position(self.side+'_stick_click')
        return {'q_m': q, 'raw_fraction': q/P['travel_m'],
                'signal': self.gamepad.gamepad_state().channel(self.side+'_stick'),
                'shaft_angle_deg': math.degrees(math.acos(cosine)), 'cosine': cosine}

    def step(self, axial_force=0., probe_force=None, collect=False):
        rows = []
        for _ in range(self.substeps):
            self.data.qfrc_applied[:] = 0
            inward, center = self.shaft()
            mj.mj_applyFT(self.model, self.data, axial_force*inward, np.zeros(3), center,
                         self.cap_id, self.data.qfrc_applied)
            if probe_force is not None:
                mj.mj_applyFT(self.model, self.data, probe_force, np.zeros(3),
                             self.data.xpos[self.probe_id], self.probe_id, self.data.qfrc_applied)
            mj.mj_step(self.model, self.data)
            if not all(np.isfinite(v).all() for v in (self.data.qpos, self.data.qvel, self.data.qacc)):
                raise RuntimeError('Nonfinite state; stopped without parameter changes')
            if any(w.number for w in self.data.warning):
                raise RuntimeError('Native warning; stopped without parameter changes')
            mj.mj_forward(self.model, self.data)
            if collect:
                rows.append({**self.sample(), **self.contacts(), 'native_time_s': float(self.data.time)})
        return rows

    def contacts(self):
        contacts, normal_vertical, total_vertical = [], 0., 0.
        for i, contact in enumerate(self.data.contact):
            ids = [int(contact.geom1), int(contact.geom2)]
            if self.probe_geom_id not in ids or not any(g in self.cap_geoms for g in ids):
                continue
            wrench = np.zeros(6)
            mj.mj_contactForce(self.model, self.data, i, wrench)
            frame = contact.frame.reshape(3, 3)
            world = frame.T @ wrench[:3]
            normal = frame[0]
            normal_vertical += abs(float(wrench[0]*(normal @ self.inward)))
            total_vertical += abs(float(world @ self.inward))
            contacts.append({'geoms': [self.model.geom(g).name for g in ids],
                'point_m': contact.pos.tolist(), 'frame_world': frame.tolist(),
                'wrench_contact_n_nm': wrench.tolist(), 'force_world_on_geom2_n': world.tolist(),
                'normal_force_n': float(wrench[0]), 'tangent_force_n': wrench[1:3].tolist()})
        return {'contacts': contacts, 'cap_contact_points': len(contacts),
                'normal_vertical_contact_n': normal_vertical, 'total_vertical_contact_n': total_vertical}

    def place_probe(self):
        plan = self.suite.case(self.side+'_x_pos').plan
        direction = np.array(plan['direction'], dtype=float)
        origin = np.array(plan['point_m'])-direction*.03
        distances = [mj.mj_rayMesh(self.model, self.data, gid, origin, direction) for gid in self.cap_geoms]
        hits = [distance for distance in distances if distance >= 0]
        if not hits:
            raise RuntimeError('Frozen upper-side ray misses native cap geometry')
        surface = origin+min(hits)*direction
        start = surface-direction*self.suite.settings['radius_m']
        self.data.joint('click_probe_free').qpos[:3] = start
        self.data.joint('click_probe_free').qvel[:] = 0
        mj.mj_forward(self.model, self.data)
        tangent = direction-self.inward*(direction @ self.inward)
        tangent /= np.linalg.norm(tangent)
        return start, tangent, {'frozen_ray_origin_m': origin.tolist(), 'frozen_ray_direction': direction.tolist(),
                               'native_surface_point_m': surface.tolist(), 'probe_start_m': start.tolist()}


def t1(output, resources):
    results = []
    p = P['T1']
    for side in ('left', 'right'):
        for angle in p['angles_deg']:
            e = Fixture(resources, side, angle)
            rows = []
            steps = round(p['ramp_up_s']/e.dt)
            with closing(ResultSink(output/f'{side}_{angle}'/'trace.jsonl')) as sink:
                for i in range(2*steps+1):
                    force = p['peak_force_n']*(i/steps if i <= steps else (2*steps-i)/steps)
                    e.step(axial_force=force)
                    inward, center = e.shaft()
                    row = {**e.sample(), 'applied_force_n': force, 'force_vector_n': (force*inward).tolist(),
                           'application_point_m': center.tolist(), 'time_s': (i+1)*e.dt, 'loading': i <= steps}
                    rows.append(row)
                    sink.write(row)
            loading = [r for r in rows if r['loading']]
            crossing = lambda level: next((r['applied_force_n'] for r in loading if r['signal'] >= level), None)
            f05, f50, f95 = [crossing(v) for v in (.05, p['trigger_signal'], .95)]
            window = f95-f05 if f95 is not None and f05 is not None else None
            expected = P['force_n']/math.cos(math.radians(angle))
            low = [r for r in rows if r['applied_force_n'] < p['low_force_fraction']*P['force_n']/r['cosine']]
            low_max = max(max(r['signal'], r['raw_fraction']) for r in low)
            angle_error = max(abs(r['shaft_angle_deg']-angle) for r in rows)
            passed = bool(low_max <= p['low_signal_max'] and window is not None and window <= p['transition_window_max_n']
                and f50 is not None and abs(f50/expected-1) <= p['trigger_relative_tolerance']
                and max(rows[-1]['signal'], rows[-1]['raw_fraction']) <= p['low_signal_max']
                and angle_error <= p['angle_hold_tolerance_deg'])
            results.append({'side': side, 'angle_deg': angle, 'trigger_force_n': f50,
                'predicted_force_n': expected, 'transition_window_n': window,
                'low_force_max_signal_or_fraction': low_max, 'final': rows[-1],
                'max_angle_error_deg': angle_error, 'passed': passed})
            save(output/'results.json', {'passed': all(r['passed'] for r in results), 'results': results})
            if not passed:
                return False
    return True


def t2(output, resources):
    results = []
    p = P['T2']
    for side in ('left', 'right'):
        for multiplier in p['force_multipliers']:
            e = Fixture(resources, side)
            rows = []
            with closing(ResultSink(output/f'{side}_{multiplier}'/'trace.jsonl')) as sink:
                for i in range(round(p['hold_s']/e.dt)):
                    e.step(axial_force=multiplier*P['force_n'])
                    row = {**e.sample(), 'time_s': (i+1)*e.dt, 'applied_force_n': multiplier*P['force_n']}
                    rows.append(row)
                    sink.write(row)
            stable = rows[-round(.5/e.dt):]
            low = max(max(r['signal'], r['raw_fraction']) for r in stable)
            high = min(min(r['signal'], r['raw_fraction']) for r in stable)
            middle = lambda samples: sum(p['middle_interval_open'][0] < r['signal'] < p['middle_interval_open'][1] for r in samples)/len(samples)
            passed = bool(low <= p['low_signal_max'] if multiplier <= p['low_multiplier_max'] else high >= p['high_signal_min'])
            results.append({'side': side, 'multiplier': multiplier, 'force_n': multiplier*P['force_n'],
                'stable_max': low, 'stable_min': high, 'middle_time_fraction': middle(rows),
                'stable_middle_time_fraction': middle(stable), 'passed': passed})
            save(output/'results.json', {'passed': all(r['passed'] for r in results), 'results': results})
            if not passed:
                return False
    return True


def t3(output, resources, *, baseline=False):
    results = []
    p = P['T3']
    for side in ('left', 'right'):
        for normal_force in p['normal_forces_n']:
            e = Fixture(resources, side, hold=False, probe=True)
            start, tangent, placement = e.place_probe()
            rows = []
            with closing(ResultSink(output/f'{side}_{normal_force}'/'trace.jsonl')) as sink:
                for i in range(round((p['push_s']+p['hold_s'])/e.dt)):
                    age = i*e.dt
                    target = start+tangent*min(p['tangent_stroke_m'], age*p['tangent_speed_m_s'])
                    velocity = np.zeros(6)
                    mj.mj_objectVelocity(e.model, e.data, mj.mjtObj.mjOBJ_BODY, e.probe_id, velocity, 0)
                    error = float((target-e.data.xpos[e.probe_id]) @ tangent)
                    tangential = np.clip(3000*error-12*float(velocity[3:] @ tangent), -16., 16.)
                    force = tangential*tangent+normal_force*e.inward-np.asarray(P['gravity_m_s2'])*e.suite.settings['mass_kg']
                    for j, row in enumerate(e.step(probe_force=force, collect=True)):
                        row.update(time_s=i*e.dt+(j+1)*e.model.opt.timestep,
                                   normal_force_command_n=normal_force, probe_force_n=force.tolist())
                        rows.append(row)
                        sink.write(row)
            scored = [r for r in rows if r['time_s'] > p['contact_settle_s'] and r['cap_contact_points']
                      and r['normal_vertical_contact_n'] < p['vertical_force_limit_n']]
            maximum = max((max(r['signal'], r['raw_fraction']) for r in scored), default=None)
            tilt = max(r['shaft_angle_deg'] for r in rows)
            passed = bool(maximum is not None and maximum <= p['signal_max_below_limit'] and tilt >= p['minimum_tilt_deg'])
            results.append({'side': side, 'normal_force_n': normal_force,
                'scored_contact_native_steps': len(scored), 'max_signal_or_fraction_below_limit': maximum,
                'max_tilt_deg': tilt, 'passed': passed, 'placement': placement})
            save(output/'results.json', {'passed': all(r['passed'] for r in results), 'baseline_comparison_only': baseline, 'results': results})
            if not passed and not baseline:
                return False
    return all(r['passed'] for r in results)


def k2b(output, resources):
    scene = load_standalone(resource_root=resources, fixed_root=True, attach_visual=False)
    e, model, data = scene.gamepad, scene.model, scene.data
    c = e._signal_controller
    initial = e.joint_positions()
    maximum = {name: 0. for name in e.gamepad_state().as_dict()}
    raw_scalar = {item.channel: 0. for item in c.scalar_mappings}
    raw_radial = {','.join(g.channels): 0. for g in c.radial_groups}
    excess = dict.fromkeys(initial, 0.)
    joint_ranges = {name: {'unit': 'm' if int(model.joint(name).type[0]) == int(mj.mjtJoint.mjJNT_SLIDE) else 'rad',
                          'minimum_q': float(value), 'maximum_q': float(value),
                          'maximum_lower_penetration': 0., 'maximum_upper_penetration': 0.,
                          'native_margin': float(model.jnt_margin[model.joint(name).id])}
                    for name, value in initial.items()}
    finite = True
    steps = round(P['settle_s']/model.opt.timestep)
    with gzip.open(output/'trace.jsonl.gz', 'wt') as sink:
        for i in range(steps+1):
            q = e.joint_positions()
            signals = e.gamepad_state().as_dict()
            for name, v in signals.items():
                maximum[name] = max(maximum[name], abs(v))
            for item in c.scalar_mappings:
                raw = max(0., min(1., (q[item.source]-item.lower)/(item.upper-item.lower)))
                raw_scalar[item.channel] = max(raw_scalar[item.channel], raw)
            axes = {item.channel: q[item.source]/(-item.lower if q[item.source] < 0 else item.upper) for item in c.axis_mappings}
            for g in c.radial_groups:
                key = ','.join(g.channels)
                raw_radial[key] = max(raw_radial[key], math.hypot(*(axes[n] for n in g.channels)))
            for name, v in q.items():
                lo, hi = model.joint(name).range
                excess[name] = max(excess[name], float(lo-v), float(v-hi))
                record = joint_ranges[name]
                record['minimum_q'] = min(record['minimum_q'], v)
                record['maximum_q'] = max(record['maximum_q'], v)
                record['maximum_lower_penetration'] = max(record['maximum_lower_penetration'], float(lo-v))
                record['maximum_upper_penetration'] = max(record['maximum_upper_penetration'], float(v-hi))
            finite = finite and all(np.isfinite(v).all() for v in (data.qpos, data.qvel, data.qacc))
            sink.write(json.dumps({'time_s': float(data.time), 'q': q, 'signals': signals, 'shaft_limits': e.tilt_limit_state()})+'\n')
            if i < steps:
                mj.mj_step(model, data)
                mj.mj_forward(model, data)
    warnings = [int(w.number) for w in data.warning]
    scalar_ok = all(raw_scalar[item.channel] <= item.neutral_epsilon for item in c.scalar_mappings)
    radial_ok = all(raw_radial[','.join(g.channels)] <= g.neutral_epsilon for g in c.radial_groups)
    # Owner ruling4 clarification explicitly retains ruling3's -1% travel
    # criterion. Signed nanometre penetration is reported, never clipped away.
    permitted_click_minimum_m = -4e-6
    click_first_step = {}
    with gzip.open(output/'trace.jsonl.gz', 'rt') as stream:
        next(stream)
        first = json.loads(next(stream))
        click_first_step = {side: first['q'][side+'_stick_click'] for side in ('left', 'right')}
    click_no_negative_penetration = all(joint_ranges[side+'_stick_click']['minimum_q'] >= 0. for side in ('left', 'right'))
    click_penetration_within_tolerance = all(
        joint_ranges[side+'_stick_click']['minimum_q'] >= permitted_click_minimum_m
        and click_first_step[side] >= permitted_click_minimum_m for side in ('left', 'right'))
    result = {'passed': bool(finite and scalar_ok and radial_ok and not any(maximum.values()) and not any(warnings)
                            and click_penetration_within_tolerance),
        'physics_dt_s': float(model.opt.timestep), 'physics_steps': steps, 'initial_qpos': initial,
        'simulation_seconds': float(data.time), 'maximum_signal_magnitude': maximum,
        'raw_scalar_maxima': raw_scalar, 'raw_radial_maxima': raw_radial,
        'maximum_joint_limit_excess': excess, 'joint_ranges': joint_ranges,
        'click_no_negative_penetration': click_no_negative_penetration,
        'click_penetration_within_tolerance': click_penetration_within_tolerance,
        'permitted_click_minimum_m': permitted_click_minimum_m,
        'click_first_step_q_m': click_first_step,
        'criteria_source': 'Owner ruling4 clarification,2026-11-07: first step and entire1s >=-4um; all channels exactly0.',
        'finite': bool(finite), 'warnings': warnings}
    save(output/'results.json', result)
    return result['passed']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', choices=['T1', 'T2', 'T3', 'K2b', 'T4'], required=True)
    parser.add_argument('--resource-root', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-comparison-only', action='store_true')
    parser.add_argument('--historical-results', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    save(args.output/'registration.json', {'sha256': hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
        'protocol': P, 'resource_root': str(Path(args.resource_root).resolve()),
        'sampling': 'T3 every native substep; T1/T2 every frozen 0.004s outer step; K2b every native substep',
        'fixture': 'Native affine tilt fixture actuators: 100 Nm/rad, 1 Nms/rad, capped 10 Nm; target ramps over first0.2s of existing1s settle. Axial load uses mj_applyFT at native cap center. No click target or state writes.',
        'K2b_criteria': {'first_step_and_1s_click_minimum_m_inclusive': -4e-6,
                         'all_channel_signals_exactly_zero': True,
                         'source': 'Owner ruling4 explicit clarification,2026-11-07'} if args.test == 'K2b' else None})
    try:
        if args.test == 'T3':
            passed = t3(args.output, args.resource_root, baseline=args.baseline_comparison_only)
        elif args.test == 'T4':
            from tests.acceptance.mujoco.executor import execute_suite
            result = execute_suite(args.output, resource_root=args.resource_root,
                                   historical_results=args.historical_results, stop_on_regression=True)
            passed = not result['regressions'] and not result.get('historical_regressions') and result['summary']['completed'] == 26
        else:
            passed = {'T1': t1, 'T2': t2, 'K2b': k2b}[args.test](args.output, args.resource_root)
    except Exception as exc:
        save(args.output/'execution_error.json', {'status': 'execution_error', 'test': args.test,
            'exception_type': type(exc).__name__, 'message': str(exc),
            'physics_passed': None, 'downstream_action': 'Stopped; no criterion or numerical parameter changes.'})
        raise
    print(json.dumps({'test': args.test, 'passed': passed}), flush=True)
    return int(not passed and not args.baseline_comparison_only)


if __name__ == '__main__':
    raise SystemExit(main())
