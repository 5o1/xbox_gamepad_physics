"""Inspect native generalized inertia/Jacobians without adding constraints."""
import argparse,json
from pathlib import Path
from isaaclab.app import AppLauncher
p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
AppLauncher.add_app_launcher_args(p);a=p.parse_args();launcher=AppLauncher(a);app=launcher.app
import torch
from isaaclab.assets import Articulation
from isaaclab.sim import SimulationContext,SimulationCfg
from xbox_gamepad_physics.isaac import build_usd,make_articulation_cfg
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.backends.common.appearance import load_appearance
from xbox_gamepad_physics.backends.common.collision import load_collision_sources
from xbox_gamepad_physics.backends.common.physical import load_physical
from xbox_gamepad_physics.backends.common.model import Pose
c=a.resources/'common/xbox_one_s';a.output.mkdir(parents=True,exist_ok=True)
motion=motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()));physical=load_physical(resource_directory=c/'physical')
appearance=load_appearance(directory=c/'visual',binding=json.loads((a.resources/'review_binding.json').read_text()))
collisions=load_collision_sources(directory=c/'collision')
sim=SimulationContext(SimulationCfg(dt=.004,device=a.device,gravity=(0.,0.,0.),log_dir=str(a.output/'logs')))
arts={}
for i,mode in enumerate(['fixed','free']):
 artifact=build_usd(a.output/(mode+'.usda'),motion=motion,physical=physical,appearance=appearance,collision_sources=collisions,visual_directory=c/'visual',root_mode=mode)
 arts[mode]=Articulation(make_articulation_cfg(artifact.usd_path,motion=motion,physical=physical,prim_path='/World/'+mode,root_pose=Pose((i*.3,0.,.1))))
sim.reset();result={}
for mode,art in arts.items():
 art.update(.004);view=art.root_physx_view
 q=art.data.joint_pos.clone();q[0,art.joint_names.index('left_stick_x')]=.2
 art.write_joint_state_to_sim(q,torch.zeros_like(q))
 art._physics_sim_view.update_articulations_kinematic()
 transforms=view.get_link_transforms().clone();mass=view.get_generalized_mass_matrices().clone();jac=view.get_jacobians().clone()
 eigen=torch.linalg.eigvalsh(mass.double())
 result[mode]={'mass_shape':list(mass.shape),'jacobian_shape':list(jac.shape),'dtype':str(mass.dtype),'device':str(mass.device),
 'minimum_mass_eigenvalue':eigen.min().item(),'maximum_mass_eigenvalue':eigen.max().item(),
 'maximum_asymmetry':(mass-mass.transpose(-1,-2)).abs().max().item(),
 'native_root_com_velocity':art.data.root_com_vel_w[0].tolist(),
 'link_transform_xyzw':transforms[0,art.body_names.index('left_stick_y_frame')].tolist(),
 'physics_view_has_update':hasattr(art._physics_sim_view,'update_articulations_kinematic')}
 torch.save({'mass':mass,'jacobian':jac,'transforms':transforms,'joint_names':art.joint_names,'body_names':art.body_names},a.output/(mode+'.pt'))
(a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);app.close(skip_cleanup=True)
