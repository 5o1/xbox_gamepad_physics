"""Native distance-row diagnostics without changing production implementation."""
import argparse,json,hashlib,os,math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from dataclasses import replace
import xml.etree.ElementTree as ET
import numpy as np
import sapien
from tests.acceptance.robotwin.stick_click import setup,save
from tests.acceptance.robotwin.executor import RobotwinPressExecutor
from tests.acceptance.records import ResultSink
from xbox_gamepad_physics.robotwin import loader,mappings

HERE=Path(__file__).resolve().parent

def fixed_setup(resources,folder,side,angle,with_distance):
 with patch('xbox_gamepad_physics.resources.resource_root',return_value=resources):desc=loader._validated_description('full_controls')
 folder.mkdir(parents=True,exist_ok=True);tree=ET.parse(desc.urdf_path)
 for j in tree.findall('joint'):
  if j.get('name')==side+'_stick_click':j.set('type','fixed')
 path=folder/'mobility.urdf';tree.write(path,encoding='utf-8',xml_declaration=True)
 (folder/'collision').symlink_to(desc.urdf_path.parent/'collision',target_is_directory=True)
 previous=sapien.physx.get_scene_config();cfg=sapien.physx.get_scene_config();cfg.gravity=[0,0,-9.81];sapien.physx.set_scene_config(cfg)
 try:scene=sapien.Scene([sapien.physx.PhysxCpuSystem()])
 finally:sapien.physx.set_scene_config(previous)
 scene.set_timestep(.004);ul=scene.create_urdf_loader();ul.fix_root_link=True;ul.load_multiple_collisions_from_file=True
 art=loader._load_sdf(ul,replace(desc,urdf_path=path),loader._sdf_physx());art.set_root_pose(sapien.Pose([0,0,.03035474591349888]))
 loader._configure_contact_material(scene,art,desc.contact_material)
 joints={j.name:j for j in art.get_active_joints()};links={l.name:l for l in art.get_links()}
 for d in desc.joint_dynamics:
  if d.name in joints:
   j=joints[d.name];j.set_drive_properties(d.stiffness,d.damping,force_limit=d.force_limit);j.set_friction(d.friction);j.set_drive_target(d.target)
 preload=dict(desc.backend_options['stick_click_preload']['generalized_preload_n']);preload.pop(side+'_stick_click');mappings.apply_preload(art,scene,preload)
 with patch('xbox_gamepad_physics.resources.resource_root',return_value=resources):motion=loader.load_motion_contract('full_controls')
 constraints,records=mappings.attach_shaft_limits(scene,SimpleNamespace(get_active_joints=lambda:[l.joint for l in art.get_links()],get_links=art.get_links),motion,desc.backend_options['shaft_tilt_limit']) if with_distance else ([],[])
 for suffix,target in [('x',math.radians(angle)),('y',0)]:
  j=joints[side+'_stick_'+suffix];j.set_drive_properties(100,1,force_limit=10,mode='force');j.set_drive_target(target)
 return SimpleNamespace(scene=scene,art=art,joints=joints,links=links,connections=constraints,fixed=True,side=side)

def measure(e,side,maximum):
 cp=e.links[side+'_stick_x_frame'];cap=e.links[side+'_stick'];conn=next((c for c in e.connections if c.entity==cap.entity),None)
 pa=conn.get_pose_in_parent() if conn else sapien.Pose([0,0,.017914745956659317]);pb=conn.get_pose_in_child() if conn else sapien.Pose([0,0,.017914745956659317])
 a=(cp.entity_pose*pa).p.astype(float);b=(cap.entity_pose*pb).p.astype(float);axis=cap.entity_pose.to_transformation_matrix()[:3,2].astype(float);neutral=e.links['controller_body'].entity_pose.to_transformation_matrix()[:3,2].astype(float)
 angle=math.degrees(math.acos(float(np.clip(axis@neutral/np.linalg.norm(axis)/np.linalg.norm(neutral),-1,1))));d=float(np.linalg.norm(b-a));idx=e.art.get_links().index(cp);w=e.art.get_link_incoming_joint_forces()[idx].tolist()
 qnames=[j.name for j in e.art.get_active_joints()];name=side+'_stick_click';q=float(e.art.get_qpos()[qnames.index(name)]) if name in qnames else None;vel=float(e.art.get_qvel()[qnames.index(name)]) if name in qnames else None
 return {'d_m':d,'d_max_m':maximum,'gap_m':maximum-d,'distance_component_readback_m':float(conn.get_distance()) if conn else None,'native_parent':conn.get_parent().name if conn else None,'parent_local_anchor_m':pa.p.tolist(),'child_local_anchor_m':pb.p.tolist(),'parent_anchor_world_m':a.tolist(),'child_anchor_world_m':b.tolist(),'parent_radius_m':float(np.linalg.norm(a-cp.entity_pose.p)),'child_radius_m':float(np.linalg.norm(b-cap.entity_pose.p)),'shaft_direction_world':axis.tolist(),'shaft_angle_deg':angle,'q_m':q,'raw_fraction':q/.0004 if q is not None else None,'qvel_m_s':vel,'incoming_click_frame_wrench':w,'distance_joint_force_n':None,'direct_force_missing_reason':'No native constraint-force getter bound by SAPIEN3.0.3'}

def run(resources,out,controls_only=False):
 os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(resources);out.mkdir(parents=True,exist_ok=True);p=HERE/'distance_slack_protocol.json';protocol=json.loads(p.read_text());save(out/'registration.json',{'protocol':protocol,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 original=RobotwinPressExecutor.setup;results=[];base=2*.017914746775954664*math.sin(math.radians(23)/2)
 conditions=[(s,a,v,False) for s in ['left','right'] for a in [18,19,20,21,22] for v in ['with_distance','without_distance','maximum_plus1mm']]+[(s,20,v,True) for s in ['left','right'] for v in ['with_distance','without_distance']]
 if controls_only:conditions=[c for c in conditions if c[3]]
 for side,angle,variant,fixed in conditions:
  name=f'{side}_{angle}_{variant}'+('_fixed_click' if fixed else '');folder=out/name;maximum=base+(.001 if variant=='maximum_plus1mm' else 0);rows=[];sink=ResultSink(folder/'trace.jsonl');captured={}
  def step_for(e):
   actual=e.scene.step
   def step():
    if fixed:
     axis=(e.links['controller_body'].entity_pose.to_transformation_matrix()[:3,2]);body=e.links[side+'_stick_x_frame'];body.add_force_at_point(7.4*axis,body.entity_pose.p)
    before=measure(e,side,maximum);actual();after=measure(e,side,maximum);row={'step':len(rows),'time_s':(len(rows)+1)*.004,'before':before,'after':after};rows.append(row);sink.write(row)
   return step
  def instrument(e,*args,**kwargs):
   original(e,*args,**kwargs);e.connections=e.gamepad._native_shaft_limits
   if variant=='maximum_plus1mm':
    for c in e.connections:c.set_limit(0,maximum,0,0)
   e.scene.step=step_for(e);captured['e']=e
  try:
   if fixed:
    e=fixed_setup(resources,folder/'asset',side,angle,variant!='without_distance');e.scene.step=step_for(e)
    for _ in range(250):e.scene.step()
   else:
    with patch.object(RobotwinPressExecutor,'setup',instrument):
     if variant=='without_distance':
      with patch.object(mappings,'attach_shaft_limits',return_value=([],[])):e=setup(side,angle)
     else:e=setup(side,angle)
   for _ in range(1500):e.scene.step()
  finally:sink.close()
  steady=[r['after'] for r in rows[-250:]];allrows=[r['after'] for r in rows];r={'condition':name,'side':side,'commanded_angle_deg':angle,'variant':variant,'fixed_click':fixed,'native_dof':e.art.dof,'steps':len(rows),'min_gap_whole_run_m':min(x['gap_m'] for x in allrows),'steady_gap_min_m':min(x['gap_m'] for x in steady),'steady_gap_max_m':max(x['gap_m'] for x in steady),'steady_fraction_mean':float(np.mean([x['raw_fraction'] for x in steady])) if not fixed else None,'steady_angle_mean_deg':float(np.mean([x['shaft_angle_deg'] for x in steady])),'final':allrows[-1]};results.append(r);save(out/'results.json',{'results':results});print(json.dumps({k:v for k,v in r.items() if k!='final'}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--controls-only',action='store_true');a=p.parse_args();run(a.resources.resolve(),a.output.resolve(),a.controls_only)
