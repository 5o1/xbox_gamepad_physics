"""Finite independent compatibility identification, never score on T1-T4."""
import os,json,math,argparse,hashlib,csv
from pathlib import Path
from unittest.mock import patch
import numpy as np
import sapien
from xbox_gamepad_physics.robotwin import load_into_scene
from xbox_gamepad_physics.backends.common.model import Parameter,Evidence

JOINTS=['left_stick_x','left_stick_y','right_stick_x','right_stick_y']
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
def parameter(v,u,protocol):
 return Parameter(float(v),u,(Evidence(str(protocol),'finite compatibility family','Simulation compatibility fitting; not hardware identified','Scale from old accepted raw excursion and approved linear spring/damping; sampled before acceptance',category='simulation_estimate'),)).as_dict()
def configuration(s,d,v,protocol,viscous_channel="native_friction",iterations=None):
 options={'joint_friction_params':{n:{'static_effort':parameter(s,'N*m',protocol),'dynamic_effort':parameter(d,'N*m',protocol),'viscous':parameter(v,'N*m*s/rad',protocol)} for n in JOINTS},'joint_friction_viscous_mapping':viscous_channel}
 if iterations is not None:
  options['solver_iterations']={key:parameter(value,'1',protocol) for key,value in zip(['position','velocity'],iterations)}
  for key,value in zip(['position','velocity'],iterations):options['solver_iterations'][key]['value']=int(value)
 return {'backend_options':{'robotwin':options}}

def trial(resources,out,hz,duration,shake,legacy=False):
 cfg=sapien.physx.get_scene_config();cfg.gravity=[0,0,0];sapien.physx.set_scene_config(cfg);scene=sapien.Scene([sapien.physx.PhysxCpuSystem()]);scene.set_timestep(1/hz)
 if legacy:
  m=json.loads((resources/'manifest.json').read_text());loader=scene.create_urdf_loader();loader.fix_root_link=False;loader.load_multiple_collisions_from_file=True;art=loader.load(str(resources/'mobility.urdf'))
  joints={j.name:j for j in art.get_active_joints()}
  for r in m['joint_dynamics']:
   j=joints[r['name']];j.set_drive_properties(r['stiffness'],r['damping'],force_limit=r['force_limit']);j.set_drive_target(r['target']);j.set_friction(.1 if j.name in JOINTS else r['friction'])
  c=m['contact_material'];material=scene.create_physical_material(c['static_friction'],c['dynamic_friction'],c['restitution'])
  for link in art.get_links():
   for shape in link.get_collision_shapes():
    shape.set_physical_material(material);shape.set_contact_offset(c['contact_offset_m']);shape.set_rest_offset(c['rest_offset_m'])
 else:
  with patch('xbox_gamepad_physics.resources.resource_root',return_value=resources):pad=load_into_scene(scene,sapien.Pose(),fixed_root=False,attach_visual=False)
  art=pad.articulation;joints={j.name:j for j in art.get_active_joints()}
 art.set_qpos(np.zeros(art.dof));art.set_qvel(np.zeros(art.dof))
 for l in art.get_links():l.disable_gravity=True
 names=[j.name for j in art.get_active_joints()];indices=[names.index(n) for n in JOINTS];body=next(l for l in art.get_links() if l.name=='controller_body');rows=[];out.mkdir(parents=True,exist_ok=True)
 with (out/'trace.jsonl').open('w') as stream:
  for i in range(int(hz*duration)):
   t=i/hz
   f=np.array([math.sin(2*math.pi*5*t),.8*math.sin(2*math.pi*7*t+.3),.6*math.sin(2*math.pi*4*t+.7)]) if shake else np.zeros(3)
   tau=np.array([.05*math.sin(2*math.pi*6*t),.04*math.sin(2*math.pi*5.5*t+.2),.03*math.sin(2*math.pi*8*t+.4)]) if shake else np.zeros(3)
   if shake:body.add_force_torque(f,tau)
   scene.step();q=art.get_qpos();vel=art.get_qvel();v=[float(q[j]) for j in indices];row={'step':i,'time_s':(i+1)/hz,'tilt_q_rad':v,'tilt_qvel_rad_s':[float(vel[j]) for j in indices],'force_n':f.tolist(),'torque_nm':tau.tolist(),'root_pose':[*map(float,art.root.entity_pose.p),*map(float,art.root.entity_pose.q)],'contact_pairs':len(scene.get_contacts()),'total_contact_impulse_ns':sum(float(np.linalg.norm(p.impulse)) for c in scene.get_contacts() for p in c.points)}
   if not np.isfinite(q).all() or not np.isfinite(vel).all():raise ValueError('non-finite calibration state')
   rows.append(row);stream.write(json.dumps(row)+'\n')
 raw=max(max(math.hypot(*r['tilt_q_rad'][:2]),math.hypot(*r['tilt_q_rad'][2:]))/math.radians(23) for r in rows)
 summary={'raw_peak':raw,'max_abs_q_rad':max(abs(q) for r in rows for q in r['tilt_q_rad']),'active_contact_steps':sum(r['total_contact_impulse_ns']>1e-12 for r in rows),'contact_steps':sum(r['contact_pairs']>0 for r in rows),'native_readback':{n:{'legacy':joints[n].get_friction(),'new':joints[n].get_friction_params().tolist(),'drive_K':joints[n].stiffness,'drive_D':joints[n].damping} for n in JOINTS},'physics':{'tgs':scene.physx_system.config.enable_tgs,'dt':scene.get_timestep(),'position_iterations':art.get_solver_position_iterations(),'velocity_iterations':art.get_solver_velocity_iterations()}}
 save(out/'summary.json',summary);return summary,np.array([r['tilt_q_rad'] for r in rows])
def main(a):
 out=a.output.resolve();protocol=json.loads(a.protocol.read_text());save(out/'registration.json',{'protocol':protocol,'sha256':hashlib.sha256(a.protocol.read_bytes()).hexdigest(),'runtime_sapien':__import__('importlib.metadata',fromlist=['version']).version('sapien')})
 baseline,reference=trial(a.old.resolve(),out/'old_replay_train',480,4,True,True);gate=abs(baseline['raw_peak']/protocol['reference']['historical_raw_radial_peak']-1)<=.1;save(out/'baseline_gate.json',{'matches_historical_aggregate':gate,'actual':baseline,'historical':protocol['reference']})
 if a.reference_only:return
 resources=a.resources.resolve();path=resources/'robotwin/full_controls/manifest.json';original=path.read_bytes();tau=.03487569187752837*.003109581535682082;D=.00023384842283830882;results=[]
 try:
  for sf in protocol['family']['static_fractions']:
   for ratio in ([0] if sf==0 else protocol['family']['dynamic_over_static']):
    for vm in protocol['family']['viscous_over_approved_drive_D']:
     ident=f's{sf}_d{ratio}_v{vm}';config=configuration(sf*tau,ratio*sf*tau,vm*D,a.protocol,protocol.get('viscous_channel','native_friction'),protocol.get('candidate_solver_iterations'));save(out/'configs'/(ident+'.json'),config);m=json.loads(original);m['backend_options']['robotwin'].update(config['backend_options']['robotwin']);path.write_text(json.dumps(m,indent=2)+'\n')
     s,q=trial(resources,out/ident,480,4,True);score=float(np.mean(((q-reference)/math.radians(23))**2));r={'id':ident,'static_Nm':sf*tau,'dynamic_Nm':ratio*sf*tau,'viscous_Nms_rad':vm*D,'raw_peak':s['raw_peak'],'score':score,'eligible':gate and s['raw_peak']<=.01 and s['active_contact_steps']==0};results.append(r);save(out/'training_results.json',{'reference_gate':gate,'results':results});print(json.dumps(r),flush=True)
  eligible=[r for r in results if r['eligible']]
  if eligible:
   best=min(r['score'] for r in eligible);selected=min([r for r in eligible if r['score']<=best*1.01],key=lambda r:(r['static_Nm'],r['dynamic_Nm'],r['viscous_Nms_rad']));config=json.loads((out/'configs'/(selected['id']+'.json')).read_text());save(out/'PROVISIONAL_SELECTED.json',{'result':selected,'scope':protocol['id']+'; independent selection, not production adoption','config':config})
   m=json.loads(original);m['backend_options']['robotwin'].update(config['backend_options']['robotwin']);path.write_text(json.dumps(m,indent=2)+'\n')
   for name,hz,dur,shake in [('static960',960,3,False),('shake240',240,4,True)]:
    old_s,_=trial(a.old.resolve(),out/('old_'+name),hz,dur,shake,True);new_s,_=trial(resources,out/('new_'+name),hz,dur,shake);save(out/(name+'_comparison.json'),{'old':old_s,'candidate':new_s,'used_for_selection':False})
  else:save(out/'NO_SELECTION.json',{'reason':'Historical replay gate or independent shake eligibility failed; no parameter adoption, no post-hoc range tuning.'})
 finally:path.write_bytes(original)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--old',type=Path,required=True);p.add_argument('--resources',type=Path);p.add_argument('--protocol',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--reference-only',action='store_true');main(p.parse_args())
