"""Replay the same archived Guide input and sample the native Isaac SDF."""
import argparse
import json
from pathlib import Path
from isaaclab.app import AppLauncher
p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--inputs',type=Path,required=True)
AppLauncher.add_app_launcher_args(p);args=p.parse_args();launcher=AppLauncher(args);app=launcher.app
import numpy as np
import torch
import omni.usd
from pxr import UsdGeom,UsdPhysics,PhysxSchema,Gf
import isaaclab.sim as sim_utils
from isaaclab.sim import SimulationContext,SimulationCfg
from isaaclab.assets import Articulation,RigidObject,RigidObjectCfg
from isaaclab.sensors import ContactSensor,ContactSensorCfg
from xbox_gamepad_physics.isaac import build_usd,make_articulation_cfg,bind_articulation
from tests.acceptance.isaac.executor import IsaacPressExecutor
from xbox_gamepad_physics.isaac.guide_clearance import SdfShapeCollection
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.backends.common.appearance import load_appearance
from xbox_gamepad_physics.backends.common.collision import load_collision_sources
from xbox_gamepad_physics.backends.common.physical import load_physical
from xbox_gamepad_physics.backends.common.model import Evidence,Parameter
from tests.acceptance.cases import load_suite
from tests.acceptance.runner import ball_force

args.output.mkdir(parents=True,exist_ok=True);r=args.resources;c=r/'common/xbox_one_s'
inputs=json.loads((args.inputs/'targets.json').read_text())
world=np.load(args.inputs/'sample_points.npz')['world_m'].reshape(-1,3)
motion=motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()))
physical=load_physical(resource_directory=c/'physical')
appearance=load_appearance(directory=c/'visual',binding=json.loads((r/'review_binding.json').read_text()))
collisions=load_collision_sources(directory=c/'collision');suite=load_suite();case=suite.case('Guide');root_pose=case.root_pose;settings=suite.settings
proof=Evidence('tests/acceptance/data/ruling20_sdf303_v1.json','fixture.sapien_mapping','Frozen shared fixture offsets.',
 'Map the existing 0.2 mm contact and zero metre rest offsets.',category='fixture_definition')
offsets={k:Parameter(suite.fixture['sapien_mapping'][k],'m',(proof,)) for k in ['contact_offset_m','rest_offset_m']}
artifact=build_usd(args.output/'controller.usda',motion=motion,physical=physical,appearance=appearance,
 collision_sources=collisions,visual_directory=c/'visual',root_mode='fixed',contact_offsets=offsets)
sim=SimulationContext(SimulationCfg(dt=.004,device=args.device,gravity=tuple(suite.fixture['gravity_m_s2']),log_dir=str(args.output/'lab_logs')))
native=Articulation(make_articulation_cfg(artifact.usd_path,motion=motion,physical=physical,root_pose=root_pose,activate_contact_sensors=True))
probe=RigidObject(RigidObjectCfg(prim_path='/World/Probe',spawn=sim_utils.SphereCfg(radius=settings['radius_m'],
 mass_props=sim_utils.MassPropertiesCfg(mass=settings['mass_kg']),rigid_props=sim_utils.RigidBodyPropertiesCfg(),
 collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=.0002,rest_offset=0.),
 physics_material=sim_utils.RigidBodyMaterialCfg(**suite.fixture['sphere_material'])),
 init_state=RigidObjectCfg.InitialStateCfg(pos=(0.,0.,.15))))
sensors={link:ContactSensor(ContactSensorCfg(prim_path='/World/Gamepad/Links/'+link,filter_prim_paths_expr=['/World/Probe'],
 track_contact_points=True,update_period=0.,max_contact_data_count_per_prim=64)) for link in ['controller_body','guide']}
sim.reset();native.update(.004);probe.update(.004);pad=bind_articulation(native,motion=motion,physical=physical)
executor=IsaacPressExecutor(simulation=sim,gamepad=pad,probe=probe,sensors=sensors,root_pose=root_pose,radius_m=settings['radius_m'])
stage=omni.usd.get_context().get_stage()
paths=[str(prim.GetPath()) for prim in stage.Traverse() if prim.HasAPI(UsdPhysics.CollisionAPI) and any('/'+link+'/' in str(prim.GetPath()) for link in ['controller_body','guide'])]
sdf=SdfShapeCollection(paths,len(world));xf=UsdGeom.XformCache();locals=[];metadata=[]
for path in sdf.object_paths:
 prim=stage.GetPrimAtPath(path);inv=xf.GetLocalToWorldTransform(prim).GetInverse()
 locals.append([tuple(inv.Transform(Gf.Vec3d(*map(float,point)))) for point in world])
 api=PhysxSchema.PhysxSDFMeshCollisionAPI(prim)
 metadata.append({'path':path,'link':'guide' if '/guide/' in path else 'controller_body',
  'resolution':api.GetSdfResolutionAttr().Get(),'margin':api.GetSdfMarginAttr().Get(),
  'narrow_band':api.GetSdfNarrowBandThicknessAttr().Get(),
  'contact_offset_m':PhysxSchema.PhysxCollisionAPI(prim).GetContactOffsetAttr().Get(),
  'rest_offset_m':PhysxSchema.PhysxCollisionAPI(prim).GetRestOffsetAttr().Get()})
values=sdf.get_sdf_and_gradients(torch.tensor(np.asarray(locals,dtype=np.float32),device=args.device)).cpu().numpy()
assert np.isfinite(values).all()
np.savez_compressed(args.output/'cooked_sdf.npz',world_m=world,gradient_xyz_distance_w=values,links=np.asarray([m['link'] for m in metadata]))
(args.output/'field_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
executor.reset_case(suite,case);start=np.asarray(case.plan['start_m']);direction=np.asarray(case.plan['direction'])
with (args.output/'trajectory.jsonl').open('w') as output:
 for target in inputs['sequence']:
  state=executor.ball_state();force=ball_force(settings,target['target_m'],state['position_m'],state['velocity_m_s'],suite.fixture['gravity_m_s2'])
  executor.apply_ball_force(force);executor.step(.004);position=executor.ball_state()['position_m'];contacts=[]
  for link,sensor in sensors.items():
   raw=sensor._contact_physx_view.get_contact_data(.004)
   assert len(raw)==6,len(raw)
   forces,points,normals,separations,counts,starts=raw
   count=int(counts.flatten()[0]);offset=int(starts.flatten()[0])
   for i in range(offset,offset+count):
    contacts.append({'link':link,'point_m':points[i].cpu().tolist(),'normal':normals[i].cpu().tolist(),
     'separation_m':float(separations[i].item()),'normal_force_n':float(forces[i].item())})
  row={**target,'actual_s_m':float(np.dot(np.asarray(position)-start,direction)),'q_m':pad.joint_positions()['guide_press'],
   'probe_position_m':position,'force_n':list(force),'contacts':contacts}
  output.write(json.dumps(row)+'\n')
(args.output/'result.json').write_text(json.dumps({'status':'completed','steps':len(inputs['sequence']),
 'sdf_source':'Isaac actual cooked SDF tensor query','sample_count_per_shape':len(world)},indent=2)+'\n')
print('ISAAC_GUIDE_COMPLETED',flush=True);app.close(skip_cleanup=True)
