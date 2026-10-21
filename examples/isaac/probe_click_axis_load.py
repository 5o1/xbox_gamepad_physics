"""Isolate native click response with axial forces and no probe/contact loop.

The frozen mechanism and passive drive remain intact. Load values are diagnostic
inputs derived from the existing return law and frozen probe force cap.
"""
import argparse
import json
from pathlib import Path
import time
import traceback
from isaaclab.app import AppLauncher

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--resources',type=Path,required=True)
p.add_argument('--source',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--stick',choices=('left','right'),required=True)
p.add_argument('--hold-s',type=float,default=2.)
AppLauncher.add_app_launcher_args(p)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
result={'status':'starting','stick':a.stick,'projection':False,'probe_present':False}
def save():
    (a.output/'result.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
save();launcher=AppLauncher(a);app=launcher.app
try:
    import numpy as np
    import torch
    from isaaclab.sim import SimulationCfg,SimulationContext
    from isaaclab.scene import InteractiveScene,InteractiveSceneCfg
    from isaaclab.utils import configclass
    from xbox_gamepad_physics.isaac import make_articulation_cfg
    from xbox_gamepad_physics.isaac.diagnostics import readback_articulation
    from xbox_gamepad_physics.isaac.shaft_limits import _rotate
    from xbox_gamepad_physics.motion import motion_from_dict
    from xbox_gamepad_physics.backends.common.physical import load_physical
    from xbox_gamepad_physics.acceptance.cases import load_suite

    c=a.resources/'common/xbox_one_s'
    motion=motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()))
    physical=load_physical(resource_directory=c/'physical');suite=load_suite()
    name=a.stick+'_stick_click';law=physical.return_laws[name]
    travel=motion.joint_by_name[name].upper;k=law.stiffness.value;neutral=law.neutral_target.value
    mass=next(x.mass_kg.value for x in physical.links if x.name==a.stick+'_stick')
    gravity=suite.fixture['gravity_m_s2']
    static_gravity_force=-mass*gravity[2]
    conditions=[{'name':'zero','force_n':0.,'static_reference_signal':0.}]
    for fraction in (.75,.95,1.):
        conditions.append({'name':f'static_reference_{fraction:g}',
            'force_n':k*(fraction*travel-neutral)-static_gravity_force,'static_reference_signal':fraction})
    conditions.append({'name':'frozen_probe_cap','force_n':suite.settings['force_limit_n'],
                       'static_reference_signal':None})
    n=len(conditions);dt=.004
    sim=SimulationContext(SimulationCfg(dt=dt,device=a.device,gravity=tuple(gravity),log_dir=str(a.output/'logs')))
    @configclass
    class SceneCfg(InteractiveSceneCfg):
        pad=make_articulation_cfg(a.source,motion=motion,physical=physical,
            prim_path='{ENV_REGEX_NS}/Gamepad',root_pose=suite.cases[0].root_pose)
    scene=InteractiveScene(SceneCfg(num_envs=n,env_spacing=.25,replicate_physics=True))
    sim.reset();scene.update(dt);art=scene['pad']
    index=art.joint_names.index(name);body=art.body_names.index(a.stick+'_stick');root_body=art.body_names.index('controller_body')
    passive=torch.tensor([physical.return_laws[j].neutral_target.value for j in art.joint_names],device=art.device).expand(n,-1).clone()
    art.set_joint_position_target(passive);art.set_joint_effort_target(torch.zeros_like(passive))
    result.update(conditions=conditions,dt_s=dt,hold_s=a.hold_s,gravity_m_s2=gravity,
        force_basis='k*(reference_fraction*travel-neutral_target)-moving_cap_mass*gravity_down; static reference only, not a fitted drive value.',
        force_application='Equal/opposite world forces on cap and fixed body, through the cap link origin along its current click axis; no probe or contact actuator.',
        native_readback=readback_articulation(art,motion=motion,physical=physical),
        physx_configuration={field:getattr(sim.cfg.physx,field) for field in (
            'solver_type','min_position_iteration_count','max_position_iteration_count',
            'min_velocity_iteration_count','max_velocity_iteration_count','enable_external_forces_every_iteration')})
    features=['q_m','joint_vel_m_s','projected_joint_force_n','load_n','tilt_x_rad','tilt_y_rad']
    phases=['rest']*25+['ramp']*125+['hold']*round(a.hold_s/dt)+['unload']*125+['recover']*125
    trace=np.zeros((len(phases),n,len(features)),dtype=np.float64)
    force=torch.zeros((n,art.num_bodies,3),device=art.device);torque=torch.zeros_like(force);positions=torch.zeros_like(force)
    env_ids=torch.arange(n,device=art.device,dtype=torch.int32)
    magnitude=torch.tensor([row['force_n'] for row in conditions],device=art.device)
    axis=torch.tensor([0.,0.,-1.],device=art.device).expand(n,-1)
    tilt_ids=[art.joint_names.index(a.stick+'_stick_'+axis) for axis in ('x','y')]
    starts={};started=time.perf_counter()
    for tick,phase in enumerate(phases):
        if phase not in starts:starts[phase]=tick
        age=tick-starts[phase]
        fraction=(age+1)/125 if phase=='ramp' else 1.-(age+1)/125 if phase=='unload' else 1. if phase=='hold' else 0.
        rotation=art.data.body_link_quat_w[:,body]
        direction=_rotate(rotation/torch.linalg.vector_norm(rotation,dim=-1,keepdim=True),axis)
        vector=direction*magnitude[:,None]*fraction
        force[:,body]=vector;force[:,root_body]=-vector
        positions[:,body]=art.data.body_link_pos_w[:,body];positions[:,root_body]=positions[:,body]
        art.write_data_to_sim()
        art.root_physx_view.apply_forces_and_torques_at_position(force,torque,positions,env_ids,True)
        sim.step(render=False);art.update(dt)
        values=torch.stack((art.data.joint_pos[:,index],art.data.joint_vel[:,index],
            art.root_physx_view.get_dof_projected_joint_forces()[:,index],magnitude*fraction,
            art.data.joint_pos[:,tilt_ids[0]],art.data.joint_pos[:,tilt_ids[1]]),-1)
        if not bool(torch.isfinite(values).all()):raise RuntimeError('nonfinite native click-axis state')
        trace[tick]=values.cpu().numpy()
    np.savez_compressed(a.output/'trace.npz',data=trace,time_s=(np.arange(len(phases))+1)*dt,
                        phases=np.asarray(phases),features=np.asarray(features))
    tail=np.flatnonzero(np.asarray(phases)=='hold')[-125:]
    result['cases']=[]
    for env,condition in enumerate(conditions):
        q=trace[tail,env,0];v=trace[tail,env,1]
        result['cases'].append({**condition,'tail_signal_min':float(q.min()/travel),
            'tail_signal_mean':float(q.mean()/travel),'tail_signal_max':float(q.max()/travel),
            'tail_q_std_m':float(q.std()),'tail_native_velocity_mean_m_s':float(v.mean()),
            'tail_position_drift_m_s':float((q[-1]-q[0])/((len(q)-1)*dt)),
            'tail_projected_joint_force_mean_n':float(trace[tail,env,2].mean())})
    result.update(status='completed',steps=len(phases),wall_seconds=time.perf_counter()-started)
    save();print('CLICK_AXIS_DONE',a.stick,result['cases'],flush=True)
except BaseException as error:
    result.update(status='execution_error',error=type(error).__name__+': '+str(error));save()
    (a.output/'failure.txt').write_text(traceback.format_exc());raise
finally:
    app.close(skip_cleanup=True)
