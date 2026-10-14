"""Ruling 5 H2c: actual displacement in velocity mode and baseline penetration.

Read existing schema-6 and incident records; never rerun or modify physics.
"""
import argparse
import json
import math
from pathlib import Path

from .finger_validate import finite
from .record import iter_records


def penetration(row):
    maximum = {'depth_m': 0., 'step': row['step'], 'bodies': [], 'finger_modes': {}}
    for contact in row['contacts']:
        fingers = [b for b in contact['bodies'] if b in (
            'main/fl_link7', 'main/fl_link8', 'secondary/fl_link7', 'secondary/fl_link8')]
        if not fingers:
            continue
        for point in contact['points']:
            depth = max(0., -point['separation_m'])
            if depth > maximum['depth_m']:
                modes = {b: row.get('finger_drives', {}).get(b.split('/')[0], {}).get(
                    b.split('/')[1].replace('link', 'joint'), {}).get('mode', 'historical_position_drive') for b in fingers}
                maximum = {'depth_m': depth, 'step': row['step'], 'bodies': contact['bodies'],
                           'finger_modes': modes, 'point': point}
    return maximum


def analyze(source, replay, prior_analysis, output):
    output.mkdir(parents=True, exist_ok=True)
    previous = json.loads((prior_analysis/'summary.json').read_text())
    original = iter_records(source)
    original_header = next(original)
    stream = iter_records(replay)
    header = next(stream)
    config = header['config']['teleop']
    speed = config['finger_drive']['speed_m_s']
    dt = previous['timestep_s']
    result = {'source': str(source), 'replay': str(replay), 'steps': 0, 'all_finite': True,
              'source_schema': original_header['schema_version'], 'new_schema': header['schema_version'],
              'compared_prefix_end_step': 39760, 'prefix_command_mismatches': 0,
              'drive_readback_passed': (not previous['drive_command_violations']
                  and not previous['drive_readback_violation_count'] and not previous['hold_target_changes']),
              'velocity_mode_finger_steps': 0, 'speed_limit_m_s': speed*1.05,
              'first_displacement_violation': None, 'maximum_velocity_mode_abs_dq_dt': None,
              'maximum_velocity_mode_abs_qvel': None,
              'old_prefix_maximum_penetration': None, 'new_prefix_maximum_penetration': None,
              'new_appended_hold_maximum_penetration': None,
              'old_step32363_maximum_penetration': None, 'new_step32363_maximum_penetration': None,
              'old_step32363_finger8_right_stick_penetration_m': 0.,
              'new_step32363_finger8_right_stick_penetration_m': 0.}
    source_steps = json.loads((replay.parent.parent/'H_results.json').read_text())['source_step_count']
    result['source_step_count'] = source_steps
    for row in stream:
        result['steps'] += 1
        result['all_finite'] &= finite(row)
        if row['step'] < source_steps:
            old = next(original)
            if old['step'] != row['step']:
                raise ValueError('source/replay step mismatch')
            if row['step'] <= 39760:
                result['prefix_command_mismatches'] += old['command'] != row['command']
                for name, r in (('old_prefix_maximum_penetration', old), ('new_prefix_maximum_penetration', row)):
                    p = penetration(r)
                    if result[name] is None or p['depth_m'] > result[name]['depth_m']:
                        result[name] = p
            if row['step'] == 32363:
                for label, r in (('old', old), ('new', row)):
                    result[label+'_step32363_maximum_penetration'] = penetration(r)
                    result[label+'_step32363_finger8_right_stick_penetration_m'] = max([0.]+[
                        max(0., -p['separation_m']) for c in r['contacts']
                        if set(c['bodies']) == {'main/fl_link8', 'gamepad/right_stick'} for p in c['points']])
        else:
            p = penetration(row)
            name = 'new_appended_hold_maximum_penetration'
            if result[name] is None or p['depth_m'] > result[name]['depth_m']:
                result[name] = p
        for role, drives in row['finger_drives'].items():
            if role == 'secondary' and not row[role]['active']:
                continue
            for joint, drive in drives.items():
                if drive['mode'] != 'velocity':
                    continue
                result['velocity_mode_finger_steps'] += 1
                index = list(row[role]['joints']).index(joint)
                qvel = row[role]['qvel'][index]
                difference = (row[role]['joints'][joint]-drive['actual_q_before_m'])/dt
                sample = {'step': row['step'], 'joint': role+'/'+joint, 'dq_dt_m_s': difference,
                          'qvel_m_s': qvel, 'q_before_m': drive['actual_q_before_m'],
                          'q_after_m': row[role]['joints'][joint]}
                if result['maximum_velocity_mode_abs_dq_dt'] is None or abs(difference) > abs(result['maximum_velocity_mode_abs_dq_dt']['dq_dt_m_s']):
                    result['maximum_velocity_mode_abs_dq_dt'] = sample
                if result['maximum_velocity_mode_abs_qvel'] is None or abs(qvel) > abs(result['maximum_velocity_mode_abs_qvel']['qvel_m_s']):
                    result['maximum_velocity_mode_abs_qvel'] = sample
                if result['first_displacement_violation'] is None and abs(difference) > speed*1.05:
                    result['first_displacement_violation'] = sample
    original.close()
    stream.close()
    result['appended_hold_steps'] = result['steps']-source_steps
    result['penetration_limit_m'] = result['old_prefix_maximum_penetration']['depth_m']+config['contact_offset_m']
    result['penetration_comparison_passed'] = result['new_prefix_maximum_penetration']['depth_m'] <= result['penetration_limit_m']
    result['passed'] = (result['drive_readback_passed'] and result['all_finite']
        and not result['first_displacement_violation'] and not result['prefix_command_mismatches']
        and result['appended_hold_steps'] == 750 and result['penetration_comparison_passed'])
    (output/'H2c_safety.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps(result, indent=2), flush=True)
    return result['passed']


def analyze_along_command(replay, prior_safety, output):
    """Ruling 6 changes only the direction of the displacement gate."""
    from .finger_passive_analysis import external_contacts
    prior = json.loads(prior_safety.read_text())
    output.mkdir(parents=True, exist_ok=True)
    result = {'ruling': 6, 'replay': str(replay), 'prior_safety': str(prior_safety),
              'steps': 0, 'velocity_mode_finger_steps': 0, 'all_finite': True,
              'speed_limit_m_s': prior['speed_limit_m_s'],
              'maximum_along_command': None, 'first_along_command_violation': None,
              'along_command_violation_count': 0, 'reverse_finger_steps': 0,
              'maximum_reverse_motion': None, 'reverse_without_direct_contact_steps': 0,
              'maximum_velocity_mode_qvel_diagnostic': None,
              'carried_drive_readback_passed': prior['drive_readback_passed'],
              'carried_penetration_comparison_passed': prior['penetration_comparison_passed'],
              'carried_prefix_command_mismatches': prior['prefix_command_mismatches'],
              'carried_appended_hold_steps': prior['appended_hold_steps']}
    dt = float(json.loads((replay.parent/'experiment.json').read_text())['config']['scene']['timestep'])
    # The record's engine timestep is float32; use the same value as rulings 4/5.
    import numpy as np
    dt = float(np.float32(dt))
    rows = iter_records(replay)
    next(rows)
    with (output/'reverse_motion.jsonl').open('w') as reverse, (output/'along_command_violations.jsonl').open('w') as failures:
        for row in rows:
            result['steps'] += 1
            result['all_finite'] &= finite(row)
            for role, drives in row['finger_drives'].items():
                if role == 'secondary' and not row[role]['active']:
                    continue
                for joint, drive in drives.items():
                    if drive['mode'] != 'velocity':
                        continue
                    result['velocity_mode_finger_steps'] += 1
                    q = row[role]['joints'][joint]
                    difference = (q-drive['actual_q_before_m'])/dt
                    along = math.copysign(1., drive['velocity_target_m_s'])*difference
                    qvel = row[role]['qvel'][list(row[role]['joints']).index(joint)]
                    sample = {'step': row['step'], 'joint': role+'/'+joint,
                              'velocity_target_m_s': drive['velocity_target_m_s'],
                              'dq_dt_m_s': difference, 'v_along_m_s': along, 'qvel_m_s': qvel,
                              'q_before_m': drive['actual_q_before_m'], 'q_after_m': q,
                              'contacts': external_contacts(row, role, joint, dt)}
                    if result['maximum_along_command'] is None or along > result['maximum_along_command']['v_along_m_s']:
                        result['maximum_along_command'] = sample
                    if result['maximum_velocity_mode_qvel_diagnostic'] is None or abs(qvel) > abs(result['maximum_velocity_mode_qvel_diagnostic']['qvel_m_s']):
                        result['maximum_velocity_mode_qvel_diagnostic'] = sample
                    if along > result['speed_limit_m_s']:
                        result['along_command_violation_count'] += 1
                        if result['first_along_command_violation'] is None:
                            result['first_along_command_violation'] = sample
                        failures.write(json.dumps({'sample': sample, 'row': row}, allow_nan=False)+'\n')
                    if along < 0:
                        result['reverse_finger_steps'] += 1
                        result['reverse_without_direct_contact_steps'] += not sample['contacts']
                        if result['maximum_reverse_motion'] is None or along < result['maximum_reverse_motion']['v_along_m_s']:
                            result['maximum_reverse_motion'] = sample
                        reverse.write(json.dumps({'classification': '外力压过驱动的被动运动（裁定6分类）',
                                                  'sample': sample, 'all_recorded_contacts': row['contacts']}, allow_nan=False)+'\n')
    rows.close()
    result['passed'] = (result['carried_drive_readback_passed'] and prior['all_finite']
        and result['all_finite'] and result['carried_penetration_comparison_passed']
        and result['carried_prefix_command_mismatches'] == 0
        and result['carried_appended_hold_steps'] == 750 and result['along_command_violation_count'] == 0)
    (output/'H2c_directional.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps(result, indent=2), flush=True)
    return result['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--prior-analysis', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--along-command', action='store_true')
    parser.add_argument('--prior-safety', type=Path)
    args = parser.parse_args()
    if args.along_command:
        if args.prior_safety is None:
            parser.error('--along-command requires --prior-safety')
        passed = analyze_along_command(args.replay, args.prior_safety, args.output)
    else:
        if args.source is None or args.prior_analysis is None:
            parser.error('ruling 5 analysis requires --source and --prior-analysis')
        passed = analyze(args.source, args.replay, args.prior_analysis, args.output)
    raise SystemExit(0 if passed else 1)
