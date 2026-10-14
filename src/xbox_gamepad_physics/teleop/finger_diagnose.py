"""Ruling 2: isolated finger-speed experiments; production control is unchanged.

A: controller far away, gravity on, floating root.
B: A with the root fixed only in this experiment.
C: B with scene gravity zero, restored before the next case.
"""
import argparse
import copy
import json
import math
from pathlib import Path

from .finger_validate import finite
from .record import iter_records, open_writer, read_header
from .runtime import make_session
from .session import Command, pose_data


def intervals(indices):
    result = []
    for index in indices:
        if result and index == result[-1][1] + 1:
            result[-1][1] = index
        else:
            result.append([index, index])
    return result


def summarize(rows, dt):
    def peak(values):
        index = max(range(len(values)), key=lambda i: abs(values[i]))
        return {'absolute_m_s': abs(values[index]), 'signed_m_s': values[index],
                'step': index, 'end_s': (index+1)*dt}
    summary = {'steps': len(rows), 'all_finite': all(finite(r) for r in rows),
               'maximum_root_speed_m_s': max(math.dist(r['root_linear_velocity_m_s'], [0]*3) for r in rows),
               'maximum_root_angular_speed_rad_s': max(math.dist(r['root_angular_velocity_rad_s'], [0]*3) for r in rows),
               'contacts': {}, 'joints': {}}
    for r in rows:
        for c in r['contacts']:
            key = ' | '.join(c['bodies'])
            summary['contacts'].setdefault(key, []).append(r['step'])
    summary['contacts'] = {k: {'first': min(v), 'last': max(v), 'steps': len(v)} for k,v in summary['contacts'].items()}
    for j in range(2):
        speeds = [r['qvel_m_s'][j] for r in rows]
        summary['joints'][str(j+7)] = {
            'peak': peak(speeds),
            # Both levels are descriptive: configured rate and the H2 tracking allowance.
            'above_0p05_steps': intervals([r['step'] for r in rows if abs(r['qvel_m_s'][j]) > .05]),
            'above_0p055_steps': intervals([r['step'] for r in rows if abs(r['qvel_m_s'][j]) > .055]),
            'ramp_peak_m_s': max(abs(r['qvel_m_s'][j]) for r in rows if r['command_target_m'] != r['drive_target_m']),
            'hold_peak_m_s': max(abs(r['qvel_m_s'][j]) for r in rows if r['command_target_m'] == r['drive_target_m']),
            'max_abs_drive_error_before_m': max(abs(r['drive_error_before_m'][j]) for r in rows),
            'max_abs_drive_error_after_m': max(abs(r['drive_error_after_m'][j]) for r in rows),
            'final_q_m': rows[-1]['q_m'][j]}
    return summary


def run(reference, output, cases=("A", "B", "C")):
    import sapien
    header = read_header(reference)
    base = header['config']
    output.mkdir(parents=True, exist_ok=True)
    initial_gravity = sapien.physx.get_scene_config().gravity.copy()
    results_path = output/'results.json'
    results = json.loads(results_path.read_text()) if results_path.exists() else {'reference': str(reference), 'cases': {}}
    for case in cases:
        scene_config = sapien.physx.get_scene_config()
        scene_config.gravity = [0, 0, 0] if case in ('C', 'C0') else initial_gravity
        sapien.physx.set_scene_config(scene_config)
        config = copy.deepcopy(base)
        config['gamepad']['pose'] = [10, 10, 10, 1, 0, 0, 0]
        config['stream']['preserve_gamepad_pose'] = True
        if case == 'C0':
            config['teleop']['fixture']['table_pose'][:2] = [10, 10]
        folder = output/case
        folder.mkdir(exist_ok=True)
        traces = []
        with open_writer(folder/'record.xgpr', 'binary') as writer, (folder/'trace.jsonl').open('w') as trace:
            session = make_session(config, folder, writer, schema_version=header["schema_version"])
            art = session.rig.main
            if case in ('B', 'C', 'C0'):
                art.root.joint.type = 'fixed'
                art.root.wake_up()
            metadata = {
                'case': case, 'config': config, 'timestep_s': session.dt,
                'gravity_m_s2': list(map(float, session.scene.physx_system.config.gravity)),
                'initial_actual_pose': pose_data(art.get_root_pose()),
                'initial_root_target_pose': list(session.rig.target),
                'initial_q_m': list(map(float, art.get_qpos())),
                'root_type': art.root.joint.type,
                'finger_drive': {j.name: {'stiffness_n_m': float(j.stiffness),
                    'damping_ns_m': float(j.damping), 'force_limit_n': float(j.force_limit),
                    'drive_velocity_target_m_s': list(map(float, j.get_drive_velocity_target()))}
                    for j in art.get_active_joints()}}
            (folder/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
            for step in range(750):
                before_q = list(map(float, art.get_qpos()))
                before_qvel = list(map(float, art.get_qvel()))
                row = session.step(Command(opening=-100) if step == 0 else Command())['state']
                target = row['finger_drive_target_m']
                r = {'step': step, 'time_end_s': row['sim_time_end_s'],
                     'q_before_m': before_q, 'q_m': list(row['main']['joints'].values()),
                     'qvel_before_m_s': before_qvel, 'qvel_m_s': row['main']['qvel'],
                     'drive_target_m': target, 'command_target_m': row['finger_command_target_m'],
                     'drive_error_before_m': [target - q for q in before_q],
                     'drive_error_after_m': [target - q for q in row['main']['joints'].values()],
                     'root_linear_velocity_m_s': row['main']['linear_velocity'],
                     'root_angular_velocity_rad_s': row['main']['angular_velocity'],
                     'root_pose': row['main']['pose'], 'root_target_pose': row['target_pose'],
                     'root_drive': row['drive'], 'contacts': row['contacts']}
                if not finite(r):
                    raise ValueError(f'{case} nonfinite step {step}')
                trace.write(json.dumps(r, allow_nan=False)+'\n')
                traces.append(r)
        results['cases'][case] = summarize(traces, session.dt)
        (output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
        print(case, json.dumps(results['cases'][case]), flush=True)
    scene_config = sapien.physx.get_scene_config()
    scene_config.gravity = initial_gravity
    sapien.physx.set_scene_config(scene_config)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=('A', 'B', 'C', 'C0'), default=['A', 'B', 'C'])
    args = parser.parse_args()
    run(args.reference, args.output, args.cases)
