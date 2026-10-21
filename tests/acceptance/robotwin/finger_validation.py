"""Ruling 3 H2a/b/c: actual-q finite differences and qvel share a 1.05*v gate."""
import argparse
import copy
import json
import math
from itertools import chain
from pathlib import Path

from xbox_gamepad_physics.teleop.record import iter_records, open_writer, read_header
from xbox_gamepad_physics.teleop.runtime import make_session
from xbox_gamepad_physics.teleop.session import Command, SCHEMA_VERSION
from xbox_gamepad_physics.teleop.site import resolve_config


def finite(value):
    if isinstance(value, dict):
        return all(finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(finite(v) for v in value)
    return not isinstance(value, float) or math.isfinite(value)


class Measurements:
    def __init__(self, speed):
        self.limit = speed*1.05
        self.steps = 0
        self.first_contacts = {}
        self.penetration_m = 0.
        self.joints = {}
        self.first_violation = None
        self.blocked_steps = 0
        self.max_force_limit_n = 0.

    def add(self, row, dt, readback):
        if not finite(row):
            raise ValueError(f"non-finite state at step {row['step']}")
        self.steps += 1
        velocities = {}
        for role, drives in row['finger_drives'].items():
            if role == 'secondary' and not row['secondary']['active']:
                continue
            for index, (name, drive) in enumerate(drives.items()):
                q = row[role]['joints'][name]
                qvel = row[role]['qvel'][index]
                difference = (q-drive['actual_q_before_m'])/dt
                key = role+'/'+name
                stats = self.joints.setdefault(key, {'maximum_abs_qvel_m_s': 0., 'maximum_abs_dq_dt_m_s': 0.})
                stats['maximum_abs_qvel_m_s'] = max(stats['maximum_abs_qvel_m_s'], abs(qvel))
                stats['maximum_abs_dq_dt_m_s'] = max(stats['maximum_abs_dq_dt_m_s'], abs(difference))
                if self.first_violation is None and max(abs(qvel), abs(difference)) > self.limit:
                    self.first_violation = {'step': row['step'], 'joint': key, 'qvel_m_s': qvel,
                                            'dq_dt_m_s': difference, 'drive': drive}
                force_limit = readback[role][name]['force_limit_n']
                self.max_force_limit_n = max(self.max_force_limit_n, force_limit)
                if drive['mode'] == 'velocity' and abs(qvel) < .005:
                    self.blocked_steps += 1
                velocities[role+'/'+name.replace('joint', 'link')] = {
                    'before_qvel_m_s': drive['actual_qvel_before_m_s'],
                    'after_qvel_m_s': qvel, 'dq_dt_m_s': difference}
        for contact in row['contacts']:
            self.penetration_m = max(self.penetration_m,
                max((max(0., -p['separation_m']) for p in contact['points']), default=0.))
            for body in contact['bodies']:
                if body in velocities:
                    key = ' | '.join(contact['bodies'])
                    self.first_contacts.setdefault(key, {'step': row['step'], 'finger': body, **velocities[body]})

    def result(self):
        return {'steps': self.steps, 'all_finite': True, 'speed_limit_m_s': self.limit,
                'joints': self.joints, 'first_violation': self.first_violation,
                'first_contacts': self.first_contacts, 'maximum_penetration_m': self.penetration_m,
                'blocked_velocity_joint_steps': self.blocked_steps,
                'maximum_readback_drive_force_limit_n': self.max_force_limit_n,
                'force_evidence': 'Native force-mode cap read back per step; not a direct drive-force sensor.',
                'passed': self.first_violation is None and self.max_force_limit_n <= 8.}


def run(source, reference, output):
    import sapien
    from xbox_gamepad_physics.examples.runner import load_config
    output.mkdir(parents=True, exist_ok=True)
    base = resolve_config(load_config(Path(__file__).with_name('templates')/'teleop_gripper.yaml'))
    reproduction = copy.deepcopy(read_header(reference)['config'])
    reproduction['teleop']['finger_drive'] = copy.deepcopy(base['teleop']['finger_drive'])
    reproduction['teleop']['robotwin_root'] = base['teleop']['robotwin_root']
    result = {'source': str(source), 'reference': str(reference), 'new_schema': SCHEMA_VERSION,
              'incident_extra_hold_steps': 750}
    def save():
        (output/'H_results.json').write_text(json.dumps(result, indent=2)+'\n')
    def episode(name, config, sequence, fixed=False, zero_gravity=False):
        folder = output/name
        folder.mkdir(parents=True, exist_ok=True)
        stats = Measurements(config['teleop']['finger_drive']['speed_m_s'])
        original_gravity = sapien.physx.get_scene_config().gravity.copy()
        if zero_gravity:
            changed = sapien.physx.get_scene_config()
            changed.gravity = [0, 0, 0]
            sapien.physx.set_scene_config(changed)
        try:
            with open_writer(folder/'record.xgpr', 'binary') as writer, (folder/'drive_readback.jsonl').open('w') as trace:
                session = make_session(config, folder, writer)
                if fixed:
                    session.rig.main.root.joint.type = 'fixed'
                    session.rig.main.root.wake_up()
                (folder/'experiment.json').write_text(json.dumps({
                    'fixed_gripper_root': fixed, 'gravity_m_s2': list(map(float, session.scene.physx_system.config.gravity)),
                    'initial_q_m': list(map(float, session.rig.main.get_qpos())),
                    'initial_root_target': session.rig.target, 'config': config}, indent=2)+'\n')
                for index, command in enumerate(sequence):
                    row = session.step(command)['state']
                    readback = {role: {j.name: {'stiffness_n_m': float(j.stiffness), 'damping_ns_m': float(j.damping),
                        'force_limit_n': float(j.force_limit), 'drive_mode': j.drive_mode,
                        'velocity_target_m_s': float(j.get_drive_velocity_target()[0])}
                        for j in getattr(session.rig, role).get_active_joints()}
                        for role in ('main', 'secondary')}
                    stats.add(row, session.dt, readback)
                    trace.write(json.dumps({'step': index, 'drives': readback}, allow_nan=False)+'\n')
                    if index and index % 5000 == 0:
                        print(name, index, flush=True)
        finally:
            restored = sapien.physx.get_scene_config()
            restored.gravity = original_gravity
            sapien.physx.set_scene_config(restored)
        measured = stats.result()
        result[name] = measured
        save()
        print(name, json.dumps(measured), flush=True)
        return measured['passed']
    commands = [Command(opening=-100)] + [Command()]*749
    if not episode('H2a', copy.deepcopy(reproduction), commands):
        return False
    c = copy.deepcopy(reproduction)
    c['gamepad']['pose'] = [10, 10, 10, 1, 0, 0, 0]
    c['stream']['preserve_gamepad_pose'] = True
    if not episode('H2b', c, commands, fixed=True, zero_gravity=True):
        return False
    stream = iter_records(source)
    header = next(stream)
    cfg = copy.deepcopy(header['config'])
    cfg['teleop']['finger_drive'] = copy.deepcopy(base['teleop']['finger_drive'])
    cfg['teleop']['robotwin_root'] = base['teleop']['robotwin_root']
    def incident_commands():
        count = 0
        for row in stream:
            count += 1
            yield Command(**row['command'])
        result['source_schema'] = header['schema_version']
        result['source_step_count'] = count
    try:
        if not episode('H2c', cfg, chain(incident_commands(), [Command()]*750)):
            return False
    finally:
        stream.close()
    from tests.acceptance.robotwin.validation import k2, k3, k4
    for name, call in (
        ('K2', lambda: k2(base, output/'K2')),
        ('K3', lambda: k3(base, output/'K3')),
        ('K4', lambda: k4(output/'H2a/record.xgpr', output/'K4')),
    ):
        (output/name).mkdir(exist_ok=True)
        measured = call()
        result[name] = measured
        save()
        print(name, json.dumps(measured), flush=True)
        if not measured['passed']:
            return False
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.source, args.reference, args.output) else 1)
