"""Review native two-hinge/cone loops without any post-step state correction.

The fixture records the inherited strict gate separately from execution. Use
--diagnostic only to characterize the already known native solver residuals.
"""
import argparse
import json
import math
from pathlib import Path
import time
import traceback

from isaaclab.app import AppLauncher

p = argparse.ArgumentParser()
p.add_argument('--resources', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--num-envs', type=int, choices=(1, 64, 1024), default=1)
p.add_argument('--root-mode', choices=('fixed', 'free'), default='fixed')
p.add_argument('--collision', choices=('sdf', 'coacd'), default='sdf')
p.add_argument('--boundary-start', action='store_true',
               help='Replay the former 22.9-degree / 2 rad/s outward-state gate.')
p.add_argument('--diagnostic', action='store_true',
               help='Record known strict-contract failures; never turn them into passes.')
AppLauncher.add_app_launcher_args(p)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
result = {'status': 'starting', 'root_mode': a.root_mode, 'num_envs': a.num_envs,
          'collision': a.collision, 'diagnostic': a.diagnostic,
          'boundary_start': a.boundary_start,
          'state_projection': False, 'checks': {}, 'strict_contract': {}, 'performance': {}}

def save():
    (a.output/'result.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')

save()
launcher = AppLauncher(a)
app = launcher.app
try:
    import torch
    from isaaclab.scene import InteractiveScene, InteractiveSceneCfg
    from isaaclab.sim import SimulationContext, SimulationCfg
    from isaaclab.utils import configclass
    from xbox_gamepad_physics.isaac import build_usd, make_articulation_cfg, bind_batched_articulation, step
    from xbox_gamepad_physics.isaac.shaft_limits import _rotate
    from xbox_gamepad_physics.isaac.diagnostics import readback_usd, readback_articulation
    from xbox_gamepad_physics.motion import motion_from_dict
    from xbox_gamepad_physics.backends.common.appearance import load_appearance
    from xbox_gamepad_physics.backends.common.collision import load_collision_sources
    from xbox_gamepad_physics.backends.common.physical import load_physical
    from xbox_gamepad_physics.backends.common.handle import ResetRequest

    def check(name, passed, **data):
        result['checks'][name] = {'passed': bool(passed), **data}
        save()
        if not passed:
            raise AssertionError(name)

    c = a.resources/'common/xbox_one_s'
    motion = motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()))
    physical = load_physical(resource_directory=c/'physical')
    appearance = load_appearance(directory=c/'visual', binding=json.loads((a.resources/'review_binding.json').read_text()))
    collisions = load_collision_sources(directory=c/'collision')
    started = time.perf_counter()
    artifact = build_usd(a.output/'pad.usda', motion=motion, physical=physical, appearance=appearance,
        collision_sources=collisions, visual_directory=c/'visual',
        root_mode=a.root_mode, collision_mode=a.collision)
    if a.collision == 'coacd':
        result['usd_readback'] = readback_usd(artifact, motion=motion, physical=physical,
                                             appearance=appearance, collision_sources=collisions)
        save()
    sim = SimulationContext(SimulationCfg(dt=.004, device=a.device, gravity=(0., 0., 0.),
                                          log_dir=str(a.output/'logs')))
    @configclass
    class SceneCfg(InteractiveSceneCfg):
        pad = make_articulation_cfg(artifact.usd_path, motion=motion, physical=physical,
                                     prim_path='{ENV_REGEX_NS}/Gamepad')
    scene = InteractiveScene(SceneCfg(num_envs=a.num_envs, env_spacing=.25, replicate_physics=True))
    sim.reset(); scene.update(.004)
    art = scene['pad']
    pad = bind_batched_articulation(art, motion=motion, physical=physical, env_origins=scene.env_origins)
    limits = pad._shaft_limits
    n = pad.num_envs
    check('native_topology', len(art.joint_names) == 20 and len(limits.limits) == 2,
          articulation_coordinates=len(art.joint_names), regular_cones=len(limits.limits),
          click_joints=[name for name in art.joint_names if name.endswith('_stick_click')])
    result['native_readback'] = readback_articulation(art, motion=motion, physical=physical)
    result['setup_and_cook_s'] = time.perf_counter()-started
    initial_root = pad.root_poses()
    zero_twist = torch.zeros((n, 6), device=pad.device)

    def reset(q=None, v=None, targets='passive'):
        pad.reset(ResetRequest(root_pose=None if art.is_fixed_base else initial_root,
            root_twist=None if art.is_fixed_base else zero_twist,
            joint_positions=q, joint_velocities=v, targets=targets))

    reset()
    before_q, before_root = pad.joint_positions(), pad.root_poses()
    illegal = before_q.clone()
    for axis in ('x', 'y'):
        illegal[:, pad._indices['left_stick_'+axis]] = motion.joint_by_name['left_stick_'+axis].upper
    rejected = False
    try:
        root = None if art.is_fixed_base else before_root.clone()
        if root is not None:
            root[:, 0] += .01
        pad.reset(ResetRequest(root_pose=root, joint_positions=illegal))
    except ValueError:
        rejected = True
    check('atomic_invalid_state', rejected and torch.equal(pad.joint_positions(), before_q)
          and torch.equal(pad.root_poses(), before_root))
    boundary = before_q.clone(); velocity = torch.zeros_like(boundary)
    index = pad._indices['left_stick_x']
    boundary[:, index] = motion.joint_by_name['left_stick_x'].upper
    velocity[:, index] = 1.
    rejected = False
    try:
        reset(boundary, velocity)
    except ValueError:
        rejected = True
    check('outward_boundary_write_rejected', rejected and torch.equal(pad.joint_positions(), before_q))
    reset(boundary)
    check('legal_state_not_projected', torch.equal(pad.joint_positions(), boundary))
    reset()
    q = pad.joint_positions()
    q[:, index] = torch.linspace(-.15, .15, n, device=pad.device)
    pad.set_joint_positions(q)
    subset = list(range(n-1, -1, -2))
    pad.set_joint_positions(q[subset], subset)
    check('subset_order', torch.equal(pad.joint_positions(subset), q[subset]))
    pad.reset(env_ids=[])
    check('empty_subset', torch.equal(pad.joint_positions(), q))
    k = n//2
    pad.reset(env_ids=[k])
    other = [i for i in range(n) if i != k]
    check('reset_one_row', torch.equal(pad.joint_positions()[other], q[other]))

    # This guard is active only inside ticks. Explicit caller resets remain legal.
    inside_tick = [False]
    calls = {'state_writes_inside_tick': 0, 'mass_requests_inside_tick': 0}
    def guard(owner, name, category):
        original = getattr(owner, name)
        def wrapped(*args, **kwargs):
            if inside_tick[0]:
                calls[category] += 1
                raise AssertionError('native tick called '+name)
            return original(*args, **kwargs)
        setattr(owner, name, wrapped)
    for name in ('write_joint_state_to_sim', 'write_joint_position_to_sim', 'write_joint_velocity_to_sim',
                 'write_root_state_to_sim', 'write_root_pose_to_sim', 'write_root_com_pose_to_sim',
                 'write_root_velocity_to_sim', 'write_root_com_velocity_to_sim'):
        guard(art, name, 'state_writes_inside_tick')
    guard(art.root_physx_view, 'get_generalized_mass_matrices', 'mass_requests_inside_tick')
    def tick(helper=True):
        inside_tick[0] = True
        try:
            if helper:
                step(sim, gamepads=(pad,))
            else:
                art.write_data_to_sim(); sim.step(render=False); art.update(.004)
        finally:
            inside_tick[0] = False

    # All twenty original drives, including both click joints, must respond.
    reset()
    start_q = pad.joint_positions()
    target = torch.tensor([motion.joint_by_name[name].lower+.65*(motion.joint_by_name[name].upper-
        motion.joint_by_name[name].lower) for name in pad.joint_names], device=pad.device).expand(n, -1)
    pad.set_joint_targets(target)
    for _ in range(100):
        tick()
    travel = torch.tensor([motion.joint_by_name[name].upper-motion.joint_by_name[name].lower
                           for name in pad.joint_names], device=pad.device)
    response = ((pad.joint_positions()-start_q)/travel).abs().amin(0)
    check('twenty_drives_respond', bool((response > .05).all()),
          minimum_normalized_response=dict(zip(pad.joint_names, response.cpu().tolist())))

    # Measure the native pipeline, without geometry reductions in timed loops.
    phase = torch.arange(n, device=pad.device)*(2*math.pi/max(n, 8))+math.pi/4
    amplitude = .98+.02*torch.arange(n, device=pad.device)/max(n-1, 1)
    targets = pad._passive.expand(n, -1).clone()
    for side, shift in (('left', 0.), ('right', math.pi/8)):
        for axis, sign in (('x', (phase+shift).cos().sign()), ('y', (phase+shift).sin().sign())):
            name = side+'_stick_'+axis
            targets[:, pad._indices[name]] = sign*amplitude*motion.joint_by_name[name].upper
    for active in (() if a.boundary_start else (False, True)):
        for helper in (False, True):
            reset()
            pad.set_joint_targets(targets if active else pad._passive.expand(n, -1))
            for _ in range(35):
                tick(helper)
            torch.cuda.synchronize(); started = time.perf_counter()
            for _ in range(100):
                tick(helper)
            torch.cuda.synchronize()
            key = ('active' if active else 'interior')+('_helper' if helper else '_sdk')
            result['performance'][key] = {'ms_per_tick': (time.perf_counter()-started)*10., 'ticks': 100}
            save()

    initial = pad._initial.expand(n, -1).clone()
    initial_velocity = torch.zeros_like(initial)
    if a.boundary_start:
        phase = torch.arange(n, device=pad.device, dtype=torch.float64)*(2*math.pi/max(n, 8))+math.pi/4
        amplitude = torch.ones(n, device=pad.device) if n == 1 else .98+.02*torch.arange(n, device=pad.device)/(n-1)
        targets = pad._passive.expand(n, -1).clone()
        for side in ('left', 'right'):
            for axis, sign in (('x', phase.cos().sign()), ('y', phase.sin().sign())):
                name = side+'_stick_'+axis
                targets[:, pad._indices[name]] = sign*amplitude*motion.joint_by_name[name].upper
        for side, shift in (('left', 0.), ('right', math.pi/8)):
            columns = [pad._indices[side+'_stick_'+axis] for axis in ('x', 'y')]
            ray = torch.stack(((phase+shift).cos(), (phase+shift).sin()), -1)
            distance = torch.full((n,), math.radians(22.9), device=pad.device, dtype=torch.float64)
            cone = 0 if side == 'left' else 1
            # Initial-state construction only, matching the previous fixture.
            for _ in range(5):
                initial[:, columns] = (distance[:, None]*ray).float()
                angles, jacobian = limits.geometry(initial)
                distance -= (angles[:, cone]-math.radians(22.9))/(jacobian[:, cone, columns]*ray).sum(-1)
            initial_velocity[:, columns] = (2.*ray).float()
        reset(initial, initial_velocity)
        result['boundary_inputs'] = {'initial_angle_deg': 22.9, 'outward_velocity_scale_rad_s': 2.,
                                     'source': 'previous hard-limit fixture; unchanged'}
    else:
        reset()
    pad.set_joint_targets(targets)
    peak = torch.zeros(2, device=pad.device, dtype=torch.float64)
    outward_peak = 0.
    native_difference = 0.
    trajectory = []
    for t in range(150):
        tick()
        angles, jacobian = limits.geometry(art.data.joint_pos)
        check_finite = bool(torch.isfinite(art.data.joint_pos).all() & torch.isfinite(art.data.joint_vel).all())
        if not check_finite:
            check('finite_state', False, tick=t)
        peak = torch.maximum(peak, angles.amax(0))
        outward = (jacobian*art.data.joint_vel.double()[:, None]).sum(-1)
        outward_peak = max(outward_peak, torch.where(angles >= limits.maximum, outward, 0.).max().item())
        if t % 10 == 0 or t == 149:
            ref = art.data.body_link_quat_w[:, art.body_names.index('controller_body')].double()
            ref = ref/torch.linalg.vector_norm(ref, dim=-1, keepdim=True)
            z = ref.new_tensor([0., 0., 1.]).expand(n, -1)
            ref_axis = _rotate(ref, z)
            native = []
            for side in ('left', 'right'):
                quat = art.data.body_link_quat_w[:, art.body_names.index(side+'_stick_y_frame')].double()
                quat = quat/torch.linalg.vector_norm(quat, dim=-1, keepdim=True)
                moving_axis = _rotate(quat, z)
                native.append(torch.atan2(torch.linalg.vector_norm(torch.linalg.cross(ref_axis, moving_axis), dim=-1),
                                         (ref_axis*moving_axis).sum(-1)))
            native = torch.stack(native, -1)
            native_difference = max(native_difference, (native-angles).abs().max().item())
        trajectory.append([t, *angles[0].tolist(), *art.data.joint_pos[0].tolist(), *art.data.joint_vel[0].tolist()])
    (a.output/'trajectory.json').write_text(json.dumps(trajectory)+'\n')
    check('native_body_axes_match_coordinates', native_difference <= 2e-6,
          maximum_difference_rad=native_difference)
    check('no_external_state_correction', all(value == 0 for value in calls.values()), **calls)
    result['strict_contract'] = {
        'every_substep_inside': {'passed': bool((peak <= limits.maximum).all()),
            'peak_angle_deg': torch.rad2deg(peak).cpu().tolist(), 'ticks': 150},
        'no_outward_boundary_velocity': {'passed': outward_peak <= 0., 'maximum_rad_s': outward_peak}}
    save()

    pad.restore_passive_targets()
    for _ in range(150):
        tick()
    result['return_angle_deg'] = torch.rad2deg(limits.geometry(art.data.joint_pos)[0].amax(0)).cpu().tolist()
    check('return_reduces_deflection', bool((limits.geometry(art.data.joint_pos)[0].amax(0) < peak).all()))

    # Keep the existing B2 row-permutation tolerances unchanged.
    if not a.boundary_start:
        initial[:, index] = torch.linspace(-.15, .15, n, device=pad.device)
    def advance(order):
        reset(initial[order], initial_velocity[order])
        pad.set_joint_targets(targets[order])
        for _ in range(12 if a.boundary_start else 20):
            tick()
        return pad.joint_positions(), pad.root_poses()
    order = torch.arange(n, device=pad.device)
    first, root_first = advance(order)
    reverse = order.flip(0)
    second, root_second = advance(reverse)
    joint_error = ((second-first[reverse])/travel).abs().max().item()
    root_error = (root_second[:, :3]-root_first[reverse, :3]).abs().max().item()
    check('row_permutation', joint_error <= 2e-4 and root_error <= 3e-6,
          normalized_joint_error=joint_error, root_position_error_m=root_error,
          tolerance_source='existing B2 D08 quantization policy')
    result['torch_allocated_bytes'] = torch.cuda.memory_allocated()
    result['torch_reserved_bytes'] = torch.cuda.memory_reserved()
    result['strict_contract_passed'] = all(row['passed'] for row in result['strict_contract'].values())
    result['status'] = 'passed' if result['strict_contract_passed'] else 'completed_with_strict_contract_failures'
    save()
    if not a.diagnostic and not result['strict_contract_passed']:
        raise AssertionError('native solver does not satisfy the inherited zero-violation contract')
    print('NATIVE_CONE_DONE '+a.root_mode+' '+str(n)+' '+result['status'], flush=True)
except BaseException as error:
    result['status'] = 'failed'
    result['error'] = type(error).__name__+': '+str(error)
    save()
    (a.output/'failure.txt').write_text(traceback.format_exc())
    print(traceback.format_exc(), flush=True)
    raise
finally:
    app.close(skip_cleanup=True)
