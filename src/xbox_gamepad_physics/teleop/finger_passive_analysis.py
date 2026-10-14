"""Ruling 4: read-only H2c classification and a URDF-based inertial estimate.

No physics replay or control mutation. Writes new analysis artifacts only.
"""
import argparse
from itertools import zip_longest
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from .finger_validate import finite
from .record import iter_records


def rotation(q):
    q = np.asarray(q, dtype=float)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def quantiles(values):
    if not values:
        return None
    return dict(zip(('min', 'p05', 'median', 'p95', 'max'),
                    map(float, np.percentile(values, [0, 5, 50, 95, 100]))))


def inertial_estimate(row, previous, role, joint, mass, com, axes, gravity, dt):
    art = row[role]
    before = previous[role] if previous is not None else art
    v0 = np.asarray(before['linear_velocity']) if previous else np.zeros(3)
    omega0 = np.asarray(before['angular_velocity']) if previous else np.zeros(3)
    acceleration = (np.asarray(art['linear_velocity'])-v0)/dt
    alpha = (np.asarray(art['angular_velocity'])-omega0)/dt
    root_pose = before['pose']
    root_rotation = rotation(root_pose[3:])
    root_com = np.asarray(root_pose[:3]) + root_rotation @ com['fl_link6']
    link = joint.replace('joint', 'link')
    link_pose = before['links'][link]
    finger_com = np.asarray(link_pose[:3]) + rotation(link_pose[3:]) @ com[link]
    lever = finger_com-root_com
    axis = root_rotation @ axes[joint]
    drive = row['finger_drives'][role][joint]
    # Moving-root acceleration evaluated at the finger COM. The Coriolis term
    # is retained explicitly; its projection onto a prismatic axis is zero.
    base_acceleration = (acceleration + np.cross(alpha, lever)
                         + np.cross(omega0, np.cross(omega0, lever))
                         + 2*np.cross(omega0, axis*drive['actual_qvel_before_m_s']))
    inertial_force = mass*float(np.dot(np.asarray(gravity)-base_acceleration, axis))
    k, c = drive['stiffness_n_m'], drive['damping_ns_m']
    error = drive['position_target_m']-drive['actual_q_before_m']
    # Implicit Euler, with measured pre-state and measured root acceleration:
    # m(v1-v0)/dt = m(g-a_base).axis + k(error-dt*v1) + c(v_target-v1).
    numerator = (mass*drive['actual_qvel_before_m_s']
                 + dt*(inertial_force+k*error+c*drive['velocity_target_m_s']))
    velocity_estimate = numerator/(mass+dt*c+dt*dt*k)
    return {'mass_kg': mass, 'root_linear_acceleration_m_s2': acceleration.tolist(),
            'root_angular_acceleration_rad_s2': alpha.tolist(), 'axis_world': axis.tolist(),
            'finger_com_lever_world_m': lever.tolist(),
            'projected_base_acceleration_m_s2': float(np.dot(base_acceleration, axis)),
            'inertial_force_n': inertial_force, 'position_error_m': error,
            'stiffness_n_m': k, 'damping_ns_m': c,
            'estimated_relative_velocity_m_s': velocity_estimate,
            'estimated_relative_displacement_m': velocity_estimate*dt}


def external_contacts(row, role, joint, dt):
    link = role+'/'+joint.replace('joint', 'link')
    pairs = {}
    for contact in row['contacts']:
        if link not in contact['bodies'] or all(b.startswith(role+'/') for b in contact['bodies']):
            continue
        other = next(b for b in contact['bodies'] if b != link)
        pair = pairs.setdefault(other, {'object': other, 'impulse_ns': [0., 0., 0.],
                                      'sum_point_impulse_norm_ns': 0., 'point_count': 0})
        for point in contact['points']:
            pair['point_count'] += 1
            pair['impulse_ns'] = [x+y for x,y in zip(pair['impulse_ns'], point['impulse_ns'])]
            pair['sum_point_impulse_norm_ns'] += math.dist(point['impulse_ns'], [0]*3)
    for pair in pairs.values():
        pair['average_force_vector_n'] = [v/dt for v in pair['impulse_ns']]
        pair['average_force_norm_n'] = math.dist(pair['average_force_vector_n'], [0]*3)
        pair['sum_point_average_force_norm_n'] = pair['sum_point_impulse_norm_ns']/dt
    return list(pairs.values())


def analyze(directory, output):
    output.mkdir(parents=True, exist_ok=True)
    source_urdf = ET.parse(directory/'derived/left_gripper.urdf').getroot()
    mass, com, axes = {}, {}, {}
    for link in source_urdf.findall('link'):
        mass[link.get('name')] = float(link.find('inertial/mass').get('value'))
        com[link.get('name')] = np.array(list(map(float, link.find('inertial/origin').get('xyz').split())))
    for joint in source_urdf.findall('joint'):
        if any(float(v) != 0 for v in joint.find('origin').get('rpy', '0 0 0').split()):
            raise ValueError('this recorded URDF has a rotated joint frame; axis transform requires review')
        axes[joint.get('name')] = np.array(list(map(float, joint.find('axis').get('xyz').split())))
    metadata = json.loads((directory/'experiment.json').read_text())
    gravity = metadata['gravity_m_s2']
    cfg = metadata['config']
    speed = cfg['teleop']['finger_drive']['speed_m_s']
    limit = speed*1.05
    # SAPIEN stores timestep and drive targets as float32. Preserve ruling 1's
    # representation tolerance for readback; commanded target is checked exactly.
    dt = float(np.float32(cfg['scene']['timestep']))
    upstream = Path(cfg['teleop']['robotwin_root'])/'assets/embodiments/aloha-agilex/urdf/arx5_description_isaac.urdf'
    original = ET.parse(upstream).getroot()
    original_masses = {link.get('name'): float(link.find('inertial/mass').get('value'))
                       for link in original.findall('link') if link.get('name') in mass}
    if mass != original_masses:
        raise ValueError('derived finger masses differ from upstream URDF')
    summary = {'record': str(directory/'record.xgpr'), 'steps': 0, 'finger_steps': 0,
               'timestep_s': dt, 'speed_limit_m_s': limit, 'mass_kg': mass,
               'upstream_urdf': str(upstream), 'derived_masses_equal_upstream': True,
               'drive_command_violations': [], 'drive_readback_violation_count': 0,
               'first_readback_violation': None, 'hold_target_changes': [],
               'maximum_readback_velocity_target_m_s': 0.,
               'maximum_readback_force_limit_n': 0., 'all_finite': True,
               'active_tested_finger_steps': 0, 'active_violations': [],
               'overspeed_categories': {'contact': 0, 'root_saturated': 0, 'neither': 0},
               'overspeed_unique_steps': {}, 'contact_object_max_average_force_n': {},
               'neither_all_gripper_contacts_empty_count': 0,
               'maximum_finger_penetration': None}
    previous = None
    last_drives = {}
    ratios, invalid_ratios, outside_ratios = [], 0, 0
    unique = {k: set() for k in summary['overspeed_categories']}
    stream = iter_records(directory/'record.xgpr')
    header = next(stream)
    readback = (json.loads(line) for line in (directory/'drive_readback.jsonl').open())
    with (output/'overspeed.jsonl').open('w') as events, (output/'neither_raw.jsonl').open('w') as unexplained:
        for row, native in zip_longest(stream, readback):
            if row is None or native is None or row['step'] != summary['steps'] or native['step'] != row['step']:
                raise ValueError('physics/readback rows are missing or noncontiguous')
            summary['steps'] += 1
            summary['all_finite'] &= finite(row) and finite(native)
            active_role = 'main' if row['state'] == 'main' else 'secondary'
            for role, drives in row['finger_drives'].items():
                if role == 'secondary' and not row[role]['active']:
                    continue
                saturated = role == active_role and row['drive']['force_saturated']
                for joint, drive in drives.items():
                    summary['finger_steps'] += 1
                    key = role+'/'+joint
                    index = list(row[role]['joints']).index(joint)
                    qvel = row[role]['qvel'][index]
                    delta = (row[role]['joints'][joint]-drive['actual_q_before_m'])/dt
                    rb = native['drives'][role][joint]
                    summary['maximum_readback_velocity_target_m_s'] = max(
                        summary['maximum_readback_velocity_target_m_s'], abs(rb['velocity_target_m_s']))
                    summary['maximum_readback_force_limit_n'] = max(
                        summary['maximum_readback_force_limit_n'], rb['force_limit_n'])
                    expected = {k: drive[k] for k in ('stiffness_n_m', 'damping_ns_m', 'force_limit_n')}
                    if (any(rb[k] != v for k,v in expected.items()) or rb['drive_mode'] != 'force'
                        or abs(rb['velocity_target_m_s']-drive['velocity_target_m_s']) > speed*1e-6):
                        summary['drive_readback_violation_count'] += 1
                        if summary['first_readback_violation'] is None:
                            summary['first_readback_violation'] = {'step': row['step'], 'joint': key, 'native': rb, 'expected': drive}
                    old = last_drives.get(key)
                    position_readback = row[role]['drive_targets'][joint]
                    if drive['mode'] == 'velocity':
                        if abs(drive['velocity_target_m_s']) > speed or abs(rb['velocity_target_m_s']) > speed*(1+1e-6):
                            summary['drive_command_violations'].append({'step': row['step'], 'joint': key, 'drive': drive, 'native': rb})
                    elif drive['mode'] == 'position_hold':
                        if old and old['mode'] == 'position_hold' and position_readback != old['position_readback_m']:
                            summary['hold_target_changes'].append({'step': row['step'], 'joint': key,
                                'before_m': old['position_readback_m'], 'after_m': position_readback,
                                'toggle': row['command']['toggle'], 'state': row['state']})
                    else:
                        summary['drive_command_violations'].append({'step': row['step'], 'joint': key, 'mode': drive['mode']})
                    last_drives[key] = {'mode': drive['mode'], 'position_readback_m': position_readback}
                    contacts = external_contacts(row, role, joint, dt)
                    overspeed = max(abs(qvel), abs(delta)) > limit
                    if drive['mode'] == 'velocity' and not contacts and not saturated:
                        summary['active_tested_finger_steps'] += 1
                        if overspeed:
                            summary['active_violations'].append({'step': row['step'], 'joint': key,
                                'qvel_m_s': qvel, 'dq_dt_m_s': delta, 'drive': drive,
                                'root_drive': row['drive'], 'all_contacts': row['contacts']})
                    if not overspeed:
                        continue
                    category = 'contact' if contacts else 'root_saturated' if saturated else 'neither'
                    summary['overspeed_categories'][category] += 1
                    unique[category].add(row['step'])
                    event = {'step': row['step'], 'joint': key, 'category': category,
                             'mode': drive['mode'], 'qvel_m_s': qvel, 'dq_dt_m_s': delta,
                             'contacts': contacts, 'root_force_saturated': saturated,
                             'root_drive': row['drive']}
                    estimate = inertial_estimate(row, previous, role, joint, mass[joint.replace('joint', 'link')], com, axes, gravity, dt)
                    event['inertial_estimate'] = estimate
                    if category == 'root_saturated':
                        predicted = abs(estimate['estimated_relative_velocity_m_s'])
                        ratio = abs(delta)/predicted if predicted > 0 else None
                        event['observed_to_estimated_dq_dt_ratio'] = ratio
                        if ratio is None or not math.isfinite(ratio):
                            invalid_ratios += 1
                            outside_ratios += 1
                        else:
                            ratios.append(ratio)
                            outside_ratios += not .3 <= ratio <= 3.
                    for contact in contacts:
                        obj = contact['object']
                        summary['contact_object_max_average_force_n'][obj] = max(
                            summary['contact_object_max_average_force_n'].get(obj, 0.), contact['average_force_norm_n'])
                    if category == 'neither':
                        summary['neither_all_gripper_contacts_empty_count'] += not any(
                            any(b.startswith(role+'/') for b in c['bodies']) for c in row['contacts'])
                        unexplained.write(json.dumps({'event': event, 'row': row, 'native_readback': native}, allow_nan=False)+'\n')
                    events.write(json.dumps(event, allow_nan=False)+'\n')
            for contact in row['contacts']:
                fingers = [b for b in contact['bodies'] if b.startswith(('main/fl_link7', 'main/fl_link8', 'secondary/fl_link7', 'secondary/fl_link8'))]
                for point in contact['points']:
                    depth = max(0., -point['separation_m'])
                    old = summary['maximum_finger_penetration']
                    if fingers and (old is None or depth > old['depth_m']):
                        modes = {finger: row['finger_drives'][finger.split('/')[0]][finger.split('/')[1].replace('link', 'joint')]['mode'] for finger in fingers}
                        summary['maximum_finger_penetration'] = {'depth_m': depth, 'step': row['step'],
                            'bodies': contact['bodies'], 'finger_modes': modes, 'point': point}
            previous = row
    stream.close()
    summary['overspeed_unique_steps'] = {k: len(v) for k,v in unique.items()}
    summary['inertial_observed_to_estimated_ratio'] = quantiles(ratios)
    summary['inertial_ratio_invalid_count'] = invalid_ratios
    summary['inertial_ratio_outside_0p3_to_3_count'] = outside_ratios
    summary['passed'] = (summary['all_finite'] and not summary['drive_command_violations']
        and not summary['drive_readback_violation_count'] and not summary['hold_target_changes']
        and not summary['active_violations'] and summary['overspeed_categories']['neither'] == 0
        and outside_ratios == 0)
    (output/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    print(json.dumps(summary, indent=2), flush=True)
    return summary['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if analyze(args.record_directory, args.output) else 1)
