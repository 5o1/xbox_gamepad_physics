"""Measure native cone error under external torque, without state projection.

Loads are diagnostic inputs. They do not change the frozen asset or drive laws.
Every condition starts in a fresh cloned environment within this application.
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
p.add_argument('--source', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--profile', choices=('drive', 'ramp', 'step', 'pulse'), required=True)
p.add_argument('--tier', choices=('low', 'high'), default='low')
p.add_argument('--torques', type=float, nargs='+')
p.add_argument('--azimuths', type=float, nargs='+', default=list(range(0, 360, 45)))
p.add_argument('--hold-s', type=float, default=1.5)
p.add_argument('--drive-seconds', type=float, default=.6)
p.add_argument('--drive-azimuths', type=float, nargs='+',
               help='Exercise drive loading in these directions instead of the historical 315-degree case.')
p.add_argument('--stick', choices=('left', 'right'), default='left')
p.add_argument('--cone-angle-scale', type=float, default=1.,
               help='Diagnostic native cone angle multiplier; common travel and scoring remain unchanged.')
p.add_argument('--initial-angle-deg', type=float, default=0.,
               help='Diagnostic initial deflection; passive drive targets remain unchanged.')
p.add_argument('--frame-style', choices=('x', 'z'), default='x')
p.add_argument('--without-cone', action='store_true')
p.add_argument('--force-every-iteration', action='store_true',
               help='Diagnostic one-factor TGS control; not an adopted backend default.')
AppLauncher.add_app_launcher_args(p)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
result = {'status': 'starting', 'completed_steps': 0, 'profile': a.profile,
          'projection': False, 'frame_style': a.frame_style, 'cone_enabled': not a.without_cone,
          'stick': a.stick, 'cone_angle_scale': a.cone_angle_scale,
          'conditions': [], 'cases': []}

def save():
    (a.output/'result.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')

save()
launcher = AppLauncher(a)
app = launcher.app

try:
    import numpy as np
    import torch
    import omni.usd
    from pxr import Gf, Usd, UsdPhysics, PhysxSchema
    from isaaclab.sim import SimulationCfg, SimulationContext
    from isaaclab.scene import InteractiveScene, InteractiveSceneCfg
    from isaaclab.utils import configclass
    from xbox_gamepad_physics.isaac import make_articulation_cfg
    from xbox_gamepad_physics.isaac.builder import _axis_quaternion
    from xbox_gamepad_physics.motion import motion_from_dict
    from xbox_gamepad_physics.backends.common.physical import load_physical
    from xbox_gamepad_physics.backends.common.model import Pose
    from tests.acceptance.cases import load_suite

    c = a.resources/'common/xbox_one_s'
    motion = motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()))
    physical = load_physical(resource_directory=c/'physical')
    if not math.isfinite(a.cone_angle_scale) or not 0. < a.cone_angle_scale <= 1.:
        raise ValueError('cone angle scale must be finite and in (0, 1]')
    cone_deg = 23.*a.cone_angle_scale
    result['native_cone_angle_deg'] = cone_deg
    reference_torque = physical.return_laws[a.stick+'_stick_x'].effort_limit.value
    frozen_case = load_suite().case(a.stick+'_x_pos')
    arm = np.asarray(frozen_case.plan['point_m'])-np.asarray(frozen_case.plan['pivot_m'])
    lever = float(np.linalg.norm(np.cross(arm, frozen_case.plan['direction'])))
    if a.torques is not None:
        torques = a.torques
    elif a.tier == 'low':
        torques = [reference_torque*x for x in (0., .1, .25, .5, 1., 2., 4., 8.)]
    else:
        torques = [16.*lever, *[reference_torque*x for x in (16., 32., 64., 128.)]]
    if a.profile == 'drive':
        torques, a.azimuths = [0.], a.drive_azimuths or [315.]
    conditions = [{'id': i, 'torque_n_m': float(torque), 'azimuth_deg': float(azimuth),
                   'equivalent_frozen_tip_force_n': float(torque/lever)}
                  for i, (torque, azimuth) in enumerate((t, d) for t in torques for d in a.azimuths)]
    result.update(conditions=conditions, dt_s=.004, hold_s=a.hold_s,
                  initial_angle_deg=a.initial_angle_deg,
                  reference_drive_limit_n_m=reference_torque,
                  reference_drive_limit_basis='existing physical ReturnLaw; a load scale, not a native constraint cap',
                  frozen_reference_lever_m=lever,
                  force_conversion_basis='norm(cross(left_x_pos.point_m - pivot_m, direction)); neutral reference only',
                  external_load_api='ArticulationView.apply_forces_and_torques_at_position; world torque pair on body and shaft frame',
                  actuator_effort_clipping_applies_to_test_load=False,
                  root_modes=['fixed', 'free'])
    if not all(math.isfinite(t) and t >= 0. for t in torques):
        raise ValueError('diagnostic torques must be finite and nonnegative')

    def quat(value):
        return Gf.Quatf(float(value[0]), Gf.Vec3f(*value[1:]))

    paths = {}
    for mode in ('fixed', 'free'):
        stage = Usd.Stage.Open(str(a.source/(mode+'.usda')))
        paths[mode] = a.output/(mode+'.usda')
        for side in ('left', 'right'):
            joint = UsdPhysics.SphericalJoint.Define(stage, '/Gamepad/ShaftLimits/'+side+'_stick_circular_limit')
            joint.CreateBody0Rel().SetTargets(['/Gamepad/Links/controller_body'])
            joint.CreateBody1Rel().SetTargets(['/Gamepad/Links/'+side+'_stick_y_frame'])
            joint.CreateLocalPos0Attr(Gf.Vec3f(*motion.joint_by_name[side+'_stick_x'].origin))
            joint.CreateLocalPos1Attr(Gf.Vec3f(0))
            joint.CreateAxisAttr(a.frame_style.upper())
            if a.frame_style == 'x':
                joint.CreateLocalRot0Attr(quat(_axis_quaternion((0., 0., 1.))))
                joint.CreateLocalRot1Attr(quat(_axis_quaternion((0., 0., 1.))))
            joint.CreateConeAngle0LimitAttr(cone_deg)
            joint.CreateConeAngle1LimitAttr(cone_deg)
            joint.CreateExcludeFromArticulationAttr(True)
            joint.CreateJointEnabledAttr(not a.without_cone)
        stage.GetRootLayer().Export(str(paths[mode]))

    sim_cfg = SimulationCfg(dt=.004, device=a.device, gravity=(0., 0., 0.), log_dir=str(a.output/'logs'))
    sim_cfg.physx.enable_external_forces_every_iteration = a.force_every_iteration
    sim = SimulationContext(sim_cfg)
    @configclass
    class SceneCfg(InteractiveSceneCfg):
        fixed_pad = make_articulation_cfg(paths['fixed'], motion=motion, physical=physical,
            prim_path='{ENV_REGEX_NS}/Fixed', root_pose=Pose((-.2, 0., .1)))
        free_pad = make_articulation_cfg(paths['free'], motion=motion, physical=physical,
            prim_path='{ENV_REGEX_NS}/Free', root_pose=Pose((.2, 0., .1)))

    scene = InteractiveScene(SceneCfg(num_envs=len(conditions), env_spacing=1., replicate_physics=True))
    sim.reset(); scene.update(.004)
    arts = [scene['fixed_pad'], scene['free_pad']]
    n = len(conditions)
    metadata = {}
    for mode, art in zip(('fixed', 'free'), arts):
        q = torch.tensor([physical.return_laws[name].initial_position.value for name in art.joint_names], device=art.device).expand(n, -1).clone()
        if not 0. <= a.initial_angle_deg < cone_deg:
            raise ValueError('initial deflection must be inside the native cone')
        if a.initial_angle_deg:
            theta = math.radians(a.initial_angle_deg)
            azimuth = torch.tensor([math.radians(c['azimuth_deg']) for c in conditions], device=art.device)
            q[:, art.joint_names.index(a.stick+'_stick_x')] = torch.atan2(
                math.sin(theta)*azimuth.cos(), torch.full_like(azimuth, math.cos(theta)))
            q[:, art.joint_names.index(a.stick+'_stick_y')] = -torch.asin(math.sin(theta)*azimuth.sin())
        art.write_joint_state_to_sim(q, torch.zeros_like(q)); art.reset()
        if not art.is_fixed_base:
            state = art.data.root_state_w.clone(); state[:, 7:] = 0.
            art.write_root_state_to_sim(state)
        targets = torch.tensor([physical.return_laws[name].neutral_target.value for name in art.joint_names], device=art.device).expand(n, -1).clone()
        if a.profile == 'drive':
            targets.zero_()
            for condition in conditions:
                direction = math.radians(condition['azimuth_deg'])
                x, y = math.cos(direction), -math.sin(direction)
                extent = max(abs(x), abs(y))
                for axis, component in (('x', x), ('y', y)):
                    targets[condition['id'], art.joint_names.index(a.stick+'_stick_'+axis)] = math.radians(23.)*component/extent
        art.set_joint_position_target(targets)
        art.set_joint_effort_target(torch.zeros_like(targets))
        art._physics_sim_view.update_articulations_kinematic()
        metadata[mode] = {'joint_names': art.joint_names, 'body_names': art.body_names,
                          'num_instances': art.num_instances, 'is_fixed_base': bool(art.is_fixed_base)}
        for name in ('get_solver_position_iteration_counts', 'get_solver_velocity_iteration_counts',
                     'get_dof_max_forces', 'get_dof_max_velocities', 'get_dof_stiffnesses', 'get_dof_dampings'):
            method = getattr(art.root_physx_view, name, None)
            metadata[mode][name] = None if method is None else method()[0].cpu().tolist()
    result['native'] = metadata
    result['physx_configuration'] = {name: getattr(sim.cfg.physx, name) for name in (
        'solver_type', 'min_position_iteration_count', 'max_position_iteration_count',
        'min_velocity_iteration_count', 'max_velocity_iteration_count', 'enable_external_forces_every_iteration')}
    template = omni.usd.get_context().get_stage()
    for mode, prim in (('fixed', 'Fixed'), ('free', 'Free')):
        api = PhysxSchema.PhysxArticulationAPI(template.GetPrimAtPath('/World/envs/env_0/'+prim))
        result['native'][mode]['schema_position_iterations'] = api.GetSolverPositionIterationCountAttr().Get()
        result['native'][mode]['schema_velocity_iterations'] = api.GetSolverVelocityIterationCountAttr().Get()

    dt = .004
    schedule = []
    def phase(name, seconds, fraction):
        count = round(seconds/dt)
        for tick in range(count):
            schedule.append((name, float(fraction(tick, count))))
    if a.profile == 'drive':
        phase('drive', a.drive_seconds, lambda tick, count: 0.)
    else:
        phase('rest', 0. if a.initial_angle_deg else .1, lambda tick, count: 0.)
        if a.profile == 'ramp':
            phase('ramp', .5, lambda tick, count: (tick+1)/count)
        if a.profile == 'pulse':
            phase('pulse', .02, lambda tick, count: 1.)
        else:
            phase('hold', a.hold_s, lambda tick, count: 1.)
        if a.profile == 'ramp':
            phase('unload', .5, lambda tick, count: 1.-(tick+1)/count)
        phase('recover', .98 if a.profile == 'pulse' else .5, lambda tick, count: 0.)

    names = arts[0].joint_names
    assert all(art.joint_names == names for art in arts)
    features = ['angle_rad', 'angle_from_q_rad', 'anchor_error_m', 'load_fraction',
                'torque_world_x', 'torque_world_y', 'torque_world_z']
    features += ['q_'+name for name in names]+['v_'+name for name in names]
    features += ['root_'+str(i) for i in range(13)]
    trace = np.lib.format.open_memmap(a.output/'trace.npy', mode='w+', dtype=np.float64,
                                     shape=(len(schedule), 2, n, len(features)))
    trace[:] = np.nan
    indices = torch.arange(n, device=a.device, dtype=torch.int32)
    tau = torch.tensor([c['torque_n_m'] for c in conditions], device=a.device)
    angle = torch.tensor([math.radians(c['azimuth_deg']) for c in conditions], device=a.device)
    torque_axis = torch.stack((-angle.sin(), angle.cos(), torch.zeros_like(angle)), -1)
    torque_buffers = [torch.zeros((n, art.num_bodies, 3), device=a.device) for art in arts]
    pivot = torch.tensor(motion.joint_by_name[a.stick+'_stick_x'].origin, device=a.device, dtype=torch.float64).expand(n, -1)
    z = pivot.new_tensor([0., 0., 1.]).expand(n, -1)
    result.update(status='running', planned_steps=len(schedule), features=features,
                  phases=[name for name, _ in schedule])
    save()

    def rotate(q, vector):
        cross = torch.linalg.cross(q[:, 1:], vector, dim=-1)
        return vector+2.*(q[:, :1]*cross+torch.linalg.cross(q[:, 1:], cross, dim=-1))

    def normalized(q):
        q = q.double()
        return q/torch.linalg.vector_norm(q, dim=-1, keepdim=True)

    started = time.perf_counter()
    for tick, (name, fraction) in enumerate(schedule):
        applied = []
        for art, buffer in zip(arts, torque_buffers):
            root = art.body_names.index('controller_body')
            moving = art.body_names.index(a.stick+'_stick_y_frame')
            orientation = art.data.body_link_quat_w[:, root]
            world_torque = rotate(orientation, torque_axis)*tau[:, None]*fraction
            buffer[:, root] = -world_torque; buffer[:, moving] = world_torque
            art.write_data_to_sim()
            # Direct body torques are independent of actuator effort clipping.
            art.root_physx_view.apply_forces_and_torques_at_position(None, buffer, None, indices, True)
            applied.append(world_torque)
        sim.step(render=False)
        invalid = False
        runaway = False
        for mode_index, art in enumerate(arts):
            art.update(dt)
            root = art.body_names.index('controller_body')
            moving = art.body_names.index(a.stick+'_stick_y_frame')
            ref_q = normalized(art.data.body_link_quat_w[:, root])
            mov_q = normalized(art.data.body_link_quat_w[:, moving])
            ref_axis = rotate(ref_q, z); mov_axis = rotate(mov_q, z)
            native_angle = torch.atan2(torch.linalg.vector_norm(torch.linalg.cross(ref_axis, mov_axis), dim=-1),
                                       (ref_axis*mov_axis).sum(-1))
            q = art.data.joint_pos
            tilt = q[:, [names.index(a.stick+'_stick_x'), names.index(a.stick+'_stick_y')]].double()
            q_angle = torch.acos(tilt.cos().prod(-1).clamp(-1., 1.))
            anchor = torch.linalg.vector_norm(art.data.body_link_pos_w[:, root].double()+rotate(ref_q, pivot)
                                             -art.data.body_link_pos_w[:, moving].double(), dim=-1)
            rows = torch.cat((native_angle[:, None], q_angle[:, None], anchor[:, None],
                native_angle.new_full((n, 1), fraction), applied[mode_index].double(),
                q.double(), art.data.joint_vel.double(), art.data.root_state_w.double()), -1)
            trace[tick, mode_index] = rows.cpu().numpy()
            invalid |= not bool(torch.isfinite(rows).all())
            runaway |= bool((native_angle > math.pi/2).any() | (tilt.abs() > math.pi).any())
        result['completed_steps'] = tick+1
        if tick % 50 == 0 or invalid or runaway:
            trace.flush()
            result['observed_max_angle_deg'] = float(np.nanmax(trace[:tick+1, :, :, 0])*180/math.pi)
            save()
        if invalid or runaway:
            result['status'] = 'numerical_failure'
            result['stop_reason'] = 'nonfinite state' if invalid else 'angle above 90deg or scalar coordinate above pi'
            break
    else:
        result['status'] = 'completed'
    trace.flush()
    done = result['completed_steps']
    phase_names = np.asarray(result['phases'][:done])
    times = (np.arange(done)+1)*dt
    hold = phase_names == ('drive' if a.profile == 'drive' else 'hold')
    if hold.any():
        hold &= times >= times[hold][-1]-.5
    for mode_index, mode in enumerate(('fixed', 'free')):
        for condition in conditions:
            index = condition['id']
            values = np.rad2deg(trace[:done, mode_index, index, 0])
            finite = np.isfinite(values)
            peak = int(np.nanargmax(values)) if finite.any() else None
            window = hold & finite
            drift = float(np.polyfit(times[window], values[window], 1)[0]) if window.sum() >= 2 else None
            result['cases'].append({**condition, 'root_mode': mode, 'finite': bool(finite.all()),
                'peak_angle_deg': float(values[peak]) if peak is not None else None,
                'peak_excess_deg': max(0., float(values[peak])-23.) if peak is not None else None,
                'peak_phase': str(phase_names[peak]) if peak is not None else None,
                'peak_time_s': float(times[peak]) if peak is not None else None,
                'hold_tail_mean_deg': float(values[window].mean()) if window.any() else None,
                'hold_tail_peak_deg': float(values[window].max()) if window.any() else None,
                'hold_tail_drift_deg_s': drift,
                'final_angle_deg': float(values[-1]) if finite[-1] else None,
                'maximum_anchor_error_m': float(np.nanmax(trace[:done, mode_index, index, 2])),
                'maximum_body_vs_q_angle_difference_rad': float(np.nanmax(np.abs(
                    trace[:done, mode_index, index, 0]-trace[:done, mode_index, index, 1])))})
    result['wall_seconds'] = time.perf_counter()-started
    save()
    print(json.dumps({'status': result['status'], 'profile': a.profile, 'conditions_per_root': n,
                      'completed_steps': done, 'maximum_angle_deg': max(c['peak_angle_deg'] for c in result['cases'])}), flush=True)
except BaseException as error:
    result.update(status='execution_error', error=type(error).__name__+': '+str(error))
    save()
    (a.output/'failure.txt').write_text(traceback.format_exc())
    print(traceback.format_exc(), flush=True)
    raise
finally:
    app.close(skip_cleanup=True)
