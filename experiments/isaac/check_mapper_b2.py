"""CUDA float32 branch comparison, independent of AppLauncher and physics.

The Python oracle receives exactly the float32-representable coordinates used
by CUDA. Zero/nonzero branch decisions, masks and device IDs require equality;
numeric tolerances apply only after branch equality has been established.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import time

import torch

from xbox_gamepad_physics.isaac.signals_torch import IsaacTorchSignalMapper
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.state import GamepadState


def oracle_inputs(motion, names, *, random_rows=4096):
    """Return deterministic float32 random, neighboring and projected cases."""
    indices = {name: index for index, name in enumerate(names)}
    generator = torch.Generator().manual_seed(20261016)
    random = torch.rand((random_rows, len(names)), generator=generator) * 2.4 - 1.2
    for index, name in enumerate(names):
        joint = motion.joint_by_name[name]
        random[:, index] *= max(abs(joint.lower), abs(joint.upper))
    rows = [torch.zeros(len(names), dtype=torch.float32)]
    controller = motion.signal_controller
    boundaries = [(mapping.source, mapping.lower + mapping.neutral_epsilon *
                   (mapping.upper - mapping.lower))
                  for mapping in controller.scalar_mappings]
    for mapping in (*controller.axis_mappings, *controller.split_mappings):
        for fraction in (0., .02, -.02, .3, -.3, 1., -1.):
            scale = -mapping.lower if fraction < 0 else mapping.upper
            boundaries.append((mapping.source, fraction * scale))
    inf = torch.tensor(float('inf'), dtype=torch.float32)
    for name, boundary in boundaries:
        pivot = torch.tensor(boundary, dtype=torch.float32)
        for value in (torch.nextafter(pivot, -inf), pivot, torch.nextafter(pivot, inf)):
            row = torch.zeros(len(names), dtype=torch.float32)
            row[indices[name]] = value
            rows.append(row)
    # Exercise the radial deadzone and saturation before D-pad closure. Each
    # component is varied by an adjacent representable float32 coordinate.
    pairs = [(group.sources, group.neutral_epsilon, group.radius)
             for group in controller.radial_source_groups]
    channel_sources = {mapping.channel: mapping.source for mapping in controller.axis_mappings}
    pairs += [(tuple(channel_sources[channel] for channel in group.channels),
               group.neutral_epsilon, group.radius) for group in controller.radial_groups]
    mappings = {mapping.source: mapping for mapping in (*controller.axis_mappings, *controller.split_mappings)}
    for pair, epsilon, radius in pairs:
        angles = [index * math.tau / 64 for index in range(64)]
        # Saturated (0.3,sqrt(1-0.3^2)) is directly adjacent to .3 closure.
        angles += [math.acos(.3), math.asin(.3)]
        for angle in angles:
            for magnitude in (epsilon, radius, 1.5 * radius):
                values = (math.cos(angle) * magnitude, math.sin(angle) * magnitude)
                row = torch.zeros(len(names), dtype=torch.float32)
                for name, value in zip(pair, values):
                    mapping = mappings[name]
                    scale = -mapping.lower if value < 0 else mapping.upper
                    row[indices[name]] = value * scale
                rows.append(row)
                for name in pair:
                    for direction in (-inf, inf):
                        neighbor = row.clone()
                        neighbor[indices[name]] = torch.nextafter(row[indices[name]], direction)
                        rows.append(neighbor)
    return torch.cat((torch.stack(rows), random))


def _compare(motion, names, q, device):
    mapper = IsaacTorchSignalMapper(motion, names, device=device)
    batch = mapper.encode(q.to(device))
    decoded = mapper.decode_joint_targets(batch)
    decoded_events = mapper.decode_event_targets(batch.events)
    actual = batch.values.cpu()
    events = batch.events.cpu()
    expected_values, expected_events, targets, event_targets = [], [], [], []
    expected_zero = []
    expected_available, expected_task, expected_actions, expected_ids = [], [], [], []
    for row, values in enumerate(q.tolist()):
        positions = dict(zip(names, values))
        oracle = mapper.controller.encode(positions)
        expected_values.append(oracle.values)
        expected_zero.append([value == 0. for value in oracle.values])
        physical_events = mapper.controller.encode_physical_events(positions)
        expected_events.append([physical_events[name] for name in mapper.event_names])
        expected_available.append(oracle.available_mask)
        expected_task.append(oracle.task_mask)
        expected_actions.append(oracle.action_mask)
        expected_ids.append(int(oracle.device_id))
        # Inverse mapping is defined on representable output, including casts.
        state = GamepadState.from_mapping(
            {name: float(actual[row, mapper.channels[name]]) for name in mapper.controller.available_channels},
            device_id=int(oracle.device_id), available_channels=mapper.controller.available_channels)
        decoded_python = mapper.controller.decode_joint_targets(state)
        targets.append([decoded_python[name] for name in decoded.names])
        event_python = mapper.controller.decode_physical_event_targets(
            {name: float(events[row, index]) for index, name in enumerate(mapper.event_names)})
        event_targets.append([event_python[name] for name in decoded_events.names])
    expected = torch.tensor(expected_values, dtype=torch.float32)
    mismatches = (actual == 0) != torch.tensor(expected_zero, dtype=torch.bool)
    if bool(mismatches.any()):
        first = mismatches.nonzero()[0].tolist()
        raise AssertionError(f'CUDA branch mismatch at row/channel {first}: {actual[tuple(first)]} != {expected[tuple(first)]}')
    torch.testing.assert_close(actual, expected, rtol=1e-6, atol=1e-7)
    torch.testing.assert_close(events, torch.tensor(expected_events, dtype=torch.float32), rtol=1e-6, atol=1e-7)
    torch.testing.assert_close(decoded.values.cpu(), torch.tensor(targets, dtype=torch.float32), rtol=1e-6, atol=1e-7)
    torch.testing.assert_close(decoded_events.values.cpu(), torch.tensor(event_targets, dtype=torch.float32), rtol=1e-6, atol=1e-7)
    for name, reference in (('available_mask', expected_available), ('task_mask', expected_task), ('action_mask', expected_actions)):
        assert torch.equal(getattr(batch, name).cpu(), torch.tensor(reference, dtype=torch.bool)), name
    assert torch.equal(batch.device_id.cpu(), torch.tensor(expected_ids, dtype=torch.int64))
    order = torch.randperm(len(q), generator=torch.Generator().manual_seed(73)).to(device)
    assert torch.equal(mapper.encode(q.to(device)[order]).values, batch.values[order])
    assert tuple(mapper.encode(q[:0].to(device)).values.shape) == (0, 32)
    task = mapper.available.clone()
    task[0] = False
    masked = mapper.encode(q[:2].to(device), task_mask=task)
    assert torch.equal(masked.task_mask, task.expand(2, -1))
    assert torch.equal(masked.action_mask, masked.available_mask & masked.task_mask)
    return {'rows': len(q), 'branches_compared': int(mismatches.numel()),
            'branch_mismatches': int(mismatches.sum()),
            'max_absolute_error': float((actual - expected).abs().max()),
            'permutation': 'pass', 'empty': 'pass', 'masks_ids': 'pass',
            'decode_game_and_events': 'pass'}


def check_mapper(motion, *, device='cuda:0', random_rows=4096):
    started = time.perf_counter()
    names = tuple(reversed(tuple(motion.joint_by_name)))
    q = oracle_inputs(motion, names, random_rows=random_rows)
    result = _compare(motion, names, q, device)
    from xbox_gamepad_physics.controller import AxisSignalMapping, GamepadSignalController, RadialSignalGroup
    partial_controller = GamepadSignalController.xbox_one_s(
        [AxisSignalMapping('left_x', 'left_stick_x', -.2, .4),
         AxisSignalMapping('left_y', 'left_stick_y', -.3, .5)],
        [RadialSignalGroup(('left_x', 'left_y'), 1., .02)])
    partial = replace(motion, signal_controller=partial_controller)
    partial_names = ('left_stick_y', 'left_stick_x')
    partial_q = oracle_inputs(partial, partial_names, random_rows=256)
    result['asymmetric_partial'] = _compare(partial, partial_names, partial_q, device)
    result.update({'status': 'pass', 'device': str(device), 'storage_dtype': 'float32',
                   'decision_dtype': 'float64', 'torch': torch.__version__,
                   'seconds': time.perf_counter() - started})
    if torch.device(device).type == 'cuda':
        result['gpu'] = torch.cuda.get_device_name(device)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--motion', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--device', default='cuda:0')
    args = parser.parse_args()
    motion = motion_from_dict(json.loads(args.motion.read_text()))
    result = check_mapper(motion, device=args.device)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
