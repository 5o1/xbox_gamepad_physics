"""CPU public-loader and physical signal smoke check for an installed wheel."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path


def run(resources: Path, output: Path) -> bool:
    import mujoco as mj
    import numpy as np
    from xbox_gamepad_physics import GamepadState, load_motion_contract
    from xbox_gamepad_physics.mujoco import load_standalone

    os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES'] = str(resources.resolve())
    scene = load_standalone(resource_root=resources, fixed_root=True, attach_visual=False)
    handle, model, data = scene.gamepad, scene.model, scene.data
    for _ in range(100):
        mj.mj_step(model, data)
    dof = model.joint('right_stick_click').dofadr[0]
    for _ in range(2000):
        data.qfrc_applied[dof] = 12.0
        mj.mj_step(model, data)
    state = handle.gamepad_state()
    positions = handle.joint_positions()
    decoded = load_motion_contract('full_controls').signal_controller.decode_joint_targets(state)
    available = [name for name in state.as_dict() if state.is_available(name)]
    restored = GamepadState.from_mapping(
        {name: state.channel(name) for name in available},
        device_id=state.device_id, available_channels=available)
    data.qfrc_applied[dof] = 0.0
    for _ in range(2000):
        mj.mj_step(model, data)
    error = abs(decoded['right_stick_click'] - positions['right_stick_click'])
    released = handle.gamepad_state().channel('right_stick')
    result = {
        'scope': 'CPU public SDF load, 4100 native steps, physical load/release and signal roundtrip; no contact suite',
        'versions': {name: importlib.metadata.version(name)
                     for name in ('xbox-gamepad-physics', 'mujoco')},
        'cpu_affinity': sorted(os.sched_getaffinity(0)),
        'native_joint_count': len(handle.joint_names),
        'timestep_s': float(model.opt.timestep), 'steps': 4100,
        'finite': bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all()),
        'signal_roundtrip': {
            'method': '12 N generalized external force on the native right click coordinate, then zero force; no state or drive-target writes',
            'loaded_signal': state.channel('right_stick'),
            'actual_q_m': positions['right_stick_click'],
            'decoded_q_m': decoded['right_stick_click'], 'decode_error_m': error,
            'serialized_values_equal': state.values == restored.values,
            'released_signal': released,
        },
    }
    result['passed'] = (result['native_joint_count'] == 20 and result['finite']
                        and state.channel('right_stick') >= .95 and error <= 1e-7
                        and released <= .05 and state.values == restored.values)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return result['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(not run(args.resources, args.output))
