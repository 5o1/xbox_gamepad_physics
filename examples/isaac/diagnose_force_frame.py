"""Isolate world-force conversion from contact and joint physics on the installed SDK."""
import argparse
import json
import math
from pathlib import Path
from isaaclab.app import AppLauncher
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
p.add_argument('--archive',type=Path,required=True)
AppLauncher.add_app_launcher_args(p);args=p.parse_args();launcher=AppLauncher(args);app=launcher.app
import numpy as np
import torch
import isaaclab.sim as sim_utils
from isaaclab.sim import SimulationContext,SimulationCfg
from isaaclab.assets import RigidObject,RigidObjectCfg
from xbox_gamepad_physics.acceptance.cases import load_suite
from xbox_gamepad_physics.acceptance.runner import ball_force
from xbox_gamepad_physics.isaac.press import IsaacPressExecutor

args.output.mkdir(parents=True,exist_ok=True);suite=load_suite();settings=suite.settings;dt=.004
sim=SimulationContext(SimulationCfg(dt=dt,device=args.device,gravity=tuple(suite.fixture['gravity_m_s2']),log_dir=str(args.output/'lab_logs')))
probe=RigidObject(RigidObjectCfg(prim_path='/World/Probe',spawn=sim_utils.SphereCfg(radius=settings['radius_m'],
 mass_props=sim_utils.MassPropertiesCfg(mass=settings['mass_kg']),rigid_props=sim_utils.RigidBodyPropertiesCfg(),
 collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=.0002,rest_offset=0.),
 physics_material=sim_utils.RigidBodyMaterialCfg(**suite.fixture['sphere_material'])),
 init_state=RigidObjectCfg.InitialStateCfg(pos=(0.,0.,.2))))
sim.reset();probe.update(dt)
# Reuse the actual adapter implementation for the legacy branch.
adapter=IsaacPressExecutor(simulation=sim,gamepad=None,probe=probe,sensors={},root_pose=None,radius_m=settings['radius_m'])
indices=torch.tensor([0],dtype=torch.int32,device=probe.device)

def apply(force,mode):
 if mode=='refresh':probe.permanent_wrench_composer.reset()
 if mode=='direct':
  f=torch.tensor([force],dtype=torch.float32,device=probe.device)
  probe.root_physx_view.apply_forces_and_torques_at_position(force_data=f,torque_data=torch.zeros_like(f),position_data=None,indices=indices,is_global=True)
  return None
 adapter.apply_ball_force(force)
 return probe.permanent_wrench_composer.composed_force_as_torch[0,0].detach().cpu().tolist()

def step(mode):
 if mode!='direct':probe.write_data_to_sim()
 sim.step(render=False);probe.update(dt)

def reset(position=(0.,0.,.2),quaternion=(1.,0.,0.,0.),angular_velocity=(0.,0.,0.)):
 state=probe.data.default_root_state.clone();state[0,:3]=torch.tensor(position,device=probe.device)
 state[0,3:7]=torch.tensor(quaternion,device=probe.device);state[0,7:]=0.
 state[0,10:13]=torch.tensor(angular_velocity,device=probe.device)
 probe.write_root_state_to_sim(state);probe.reset()

result={'fixture':{'mass_kg':settings['mass_kg'],'radius_m':settings['radius_m'],'dt_s':dt,
 'sphere_pd':settings,'gravity_m_s2':suite.fixture['gravity_m_s2'],'scene':'one free sphere, no controller or contacts'},
 'orientation_test':[],'empty_replay':[],'spin_stimulus':{'angular_velocity_rad_s':[0.,0.,2*math.pi],
 'basis':'Diagnostic initial condition: one revolution per second; not an adopted physical parameter.'}}
for mode in ['legacy','refresh','direct']:
 reset()
 force=[1.,0.,settings['mass_kg']*9.81]
 apply(force,mode);step(mode)
 # Only rotate and reset velocity; preserve the old composer's cached pose.
 state=probe.data.root_state_w.clone();state[0,3:7]=torch.tensor([math.sqrt(.5),0.,0.,math.sqrt(.5)],device=probe.device)
 state[0,7:]=0.;probe.write_root_state_to_sim(state)
 local=apply(force,mode);step(mode)
 actual=probe.data.root_lin_vel_w[0].cpu().numpy()
 result['orientation_test'].append({'mode':mode,'world_force_n':force,'composed_local_force_n':local,
  'actual_delta_velocity_m_s':actual.tolist(),'expected_delta_velocity_m_s':[dt/settings['mass_kg'],0.,0.]})
for name in ['left_x_pos','left_x_neg','right_x_neg']:
 folder='r4_sdf_15' if name.startswith('left') else 'r4_sdf_21'
 rows=[json.loads(line) for line in (args.archive/'output'/folder/f'trace_{name}.jsonl').open()]
 for spin in [False,True]:
  for mode in ['legacy','refresh','direct']:
   reset(position=rows[0]['probe']['pose'][:3],angular_velocity=(0.,0.,2*math.pi) if spin else (0.,0.,0.))
   maximum=0.;force_error=0.;maximum_speed=0.;last_error=0.
   with (args.output/f'empty_{name}_{mode}_{"spin" if spin else "still"}.jsonl').open('w') as output:
    for row in rows:
     position=probe.data.root_pos_w[0].cpu().tolist();velocity=probe.data.root_lin_vel_w[0].cpu().tolist()
     force=ball_force(settings,row['probe']['target_m'],position,velocity,suite.fixture['gravity_m_s2'])
     q=probe.data.root_quat_w[0].cpu().tolist();local=apply(force,mode)
     if local is not None:
      from xbox_gamepad_physics.backends.common.transforms import rotate
      force_error=max(force_error,math.dist(rotate(q,local),force))
     step(mode);position=probe.data.root_pos_w[0].cpu().tolist()
     error=math.dist(position,row['probe']['target_m']);maximum=max(maximum,error);last_error=error
     speed=float(torch.linalg.vector_norm(probe.data.root_lin_vel_w[0]).item());maximum_speed=max(maximum_speed,speed)
     output.write(json.dumps({'step':row['step'],'phase':row['probe']['phase'],'position_m':position,
      'target_m':row['probe']['target_m'],'force_n':force,'composed_local_force_n':local,'quaternion_wxyz':q,
      'tracking_error_m':error,'speed_m_s':speed})+'\n')
   result['empty_replay'].append({'case':name,'mode':mode,'spin':spin,'steps':len(rows),
    'max_tracking_error_m':maximum,'final_tracking_error_m':last_error,'max_speed_m_s':maximum_speed,
    'max_world_force_direction_error_n':force_error if mode!='direct' else None})
   (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
   print('EMPTY_DONE',name,mode,spin,maximum,flush=True)
(args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('FORCE_FRAME_DONE',flush=True)
app.close(skip_cleanup=True)
