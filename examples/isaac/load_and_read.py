"""Load the experimental native asset and read canonical gamepad signals.

The caller owns AppLauncher, the scene, reset and stepping. This isolated
zero-gravity drive demonstration is not a contact-acceptance test.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path


def main():
    from isaaclab.app import AppLauncher
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root-mode', choices=['fixed', 'free'], default='fixed')
    parser.add_argument('--num-envs', type=int, choices=[1, 64], default=1)
    parser.add_argument('--build', action='store_true', help='Regenerate USD in the output directory')
    parser.add_argument('--drive-demo', action='store_true', help='Drive A, measure response, then restore passive targets')
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    app = AppLauncher(args).app
    try:
        from isaaclab.assets import Articulation
        from isaaclab.scene import InteractiveScene, InteractiveSceneCfg
        from isaaclab.sim import SimulationCfg, SimulationContext
        from isaaclab.utils import configclass
        from xbox_gamepad_physics.backends.common.physical import load_physical
        from xbox_gamepad_physics.isaac import (
            bind_articulation, bind_batched_articulation, build_usd,
            make_articulation_cfg, step,
        )
        from xbox_gamepad_physics.motion import motion_from_dict
        from xbox_gamepad_physics.state import CHANNEL_NAMES, TENSOR_LAYOUT_ID

        args.output.mkdir(parents=True, exist_ok=True)
        common = args.resources / 'common/xbox_one_s'
        motion = motion_from_dict(json.loads((common / 'motion/full_controls.json').read_text()))
        physical = load_physical(resource_directory=common / 'physical')
        usd = args.resources / 'usd' / (args.root_mode + '.usda')
        if args.build:
            from xbox_gamepad_physics.backends.common.appearance import load_appearance
            from xbox_gamepad_physics.backends.common.collision import load_collision_sources
            appearance = load_appearance(directory=common / 'visual', binding=json.loads(
                (args.resources / 'review_binding.json').read_text()))
            usd = build_usd(args.output / (args.root_mode + '.usda'), motion=motion,
                            physical=physical, appearance=appearance,
                            collision_sources=load_collision_sources(directory=common / 'collision'),
                            visual_directory=common / 'visual', root_mode=args.root_mode).usd_path
        if not usd.is_file():
            raise FileNotFoundError('Extract the prepared resources first, or use --build')

        dt = .004  # Existing demonstration timestep; not a calibrated physical parameter.
        sim = SimulationContext(SimulationCfg(dt=dt, device=args.device, gravity=(0., 0., 0.),
                                             log_dir=str(args.output / 'lab_logs')))
        if args.num_envs == 1:
            native = Articulation(make_articulation_cfg(usd, motion=motion, physical=physical))
            sim.reset()
            native.update(dt)
            handle = bind_articulation(native, motion=motion, physical=physical)
            first = handle
        else:
            @configclass
            class SceneCfg(InteractiveSceneCfg):
                pad = make_articulation_cfg(usd, motion=motion, physical=physical,
                                            prim_path='{ENV_REGEX_NS}/Gamepad')
            scene = InteractiveScene(SceneCfg(num_envs=args.num_envs, env_spacing=.25,
                                              replicate_physics=True))
            sim.reset()
            scene.update(dt)
            native = scene['pad']
            handle = bind_batched_articulation(native, motion=motion, physical=physical,
                                               env_origins=scene.env_origins)
            first = handle.select(0)
        if bool(native.is_fixed_base) != (args.root_mode == 'fixed'):
            raise ValueError('Loaded root mode differs from requested birth mode')
        result = {
            'scope': 'load, named drive and canonical signal readout; contact qualification is separate',
            'root_mode': args.root_mode, 'num_envs': args.num_envs,
            'versions': {n: importlib.metadata.version(n) for n in ['isaaclab', 'isaacsim', 'torch']},
            'joint_names': list(first.joint_names),
            'tensor_layout_id': TENSOR_LAYOUT_ID, 'channel_names': list(CHANNEL_NAMES),
            'gravity_m_s2': [0., 0., 0.], 'dt_s': dt,
        }

        def capture():
            state = first.gamepad_state()
            return {'values': list(state.values), 'available_mask': list(state.available_mask),
                    'task_mask': list(state.task_mask), 'device_id': state.device_id,
                    'physical_events': first.physical_events()}

        result['initial_signals'] = capture()
        if args.drive_demo:
            from xbox_gamepad_physics.state import GamepadState
            # The shared mapper owns the named-control to joint relationship.
            first.set_gamepad_targets(GamepadState.xbox_one_s({'south': .65}))
            for _ in range(100):
                step(sim, gamepads=(handle,))
            result['driven_signals'] = capture()
            handle.restore_passive_targets()
        for _ in range(100):
            step(sim, gamepads=(handle,))
        result['final_signals'] = capture()
        if args.num_envs > 1:
            batch = handle.gamepad_state()
            result['batch_shape'] = list(batch.values.shape)
            result['batch_device'] = str(batch.values.device)
        result['status'] = 'completed'
        (args.output / 'preview_result.json').write_text(json.dumps(result, indent=2) + '\n')
        print('ISAAC_PREVIEW', args.root_mode, args.num_envs, flush=True)
    finally:
        app.close(skip_cleanup=True)


if __name__ == '__main__':
    main()
