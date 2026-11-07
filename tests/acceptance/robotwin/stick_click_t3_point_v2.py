"""Owner-approved point-force T3v2 on a caller-selected immutable snapshot."""
import argparse,json,hashlib,math
from pathlib import Path
import numpy as np
from tests.acceptance.robotwin.executor import RobotwinPressExecutor
from tests.acceptance import load_suite
from tests.acceptance.records import ResultSink
from tests.acceptance.robotwin.stick_click import save
P=Path(__file__).with_name('stick_click_t3_point_v2.json')

def cap_point(link,local_direction):
 meshes=[]
 for shape in link.get_collision_shapes():
  transform=shape.local_pose.to_transformation_matrix();v=np.asarray(shape.get_vertices(),dtype=float)*np.asarray(shape.get_scale());v=v@transform[:3,:3].T+transform[:3,3];f=np.asarray(shape.get_triangles()).reshape(-1,3);meshes.append((v,f))
 vertices,faces=max(meshes,key=lambda m:m[0][:,2].max());center=(vertices.min(0)+vertices.max(0))/2
 radial=np.asarray(local_direction,dtype=float).copy();radial[2]=0;radial/=np.linalg.norm(radial)
 # Directional half-width, measured on the actual top-cap mesh component.
 extent=vertices@radial;radius=float((extent.max()-extent.min())/2);xy=(center+.5*radius*radial)[:2];hits=[]
 for i,tri in enumerate(vertices[faces]):
  a,b,c=tri;matrix=np.column_stack((b[:2]-a[:2],c[:2]-a[:2]))
  if abs(np.linalg.det(matrix))<1e-15:continue
  u,v=np.linalg.solve(matrix,xy-a[:2])
  if u>=-1e-8 and v>=-1e-8 and u+v<=1+1e-8:hits.append((float(a[2]+u*(b[2]-a[2])+v*(c[2]-a[2])),i,float(u),float(v)))
 if not hits:raise ValueError('registered point ray misses actual cap triangles')
 z,i,u,v=max(hits);return {'point_local_m':[float(xy[0]),float(xy[1]),z],'center_xy_local_m':center[:2].tolist(),'radius_m':radius,'direction_local':radial.tolist(),'triangle_index':i,'barycentric_uv':[u,v],'vertices_local_m':vertices.tolist(),'triangles':faces.tolist()}

def run(resources,out,model,cases=None):
 import os
 os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(resources.resolve());p=json.loads(P.read_text());out.mkdir(parents=True,exist_ok=True);save(out/'registration.json',{'protocol':p,'sha256':hashlib.sha256(P.read_bytes()).hexdigest(),'model':model,'resources':str(resources.resolve())});suite=load_suite();results=[]
 for side in p['sides']:
  for fv in p['force']['vertical_levels_n']:
   if cases is not None and (side,fv) not in cases:continue
   e=RobotwinPressExecutor();case=suite.case('L3' if side=='left' else 'R3');e.setup([*case.root_pose.position_m,*case.root_pose.orientation_wxyz],p['dt_s']);cap=e.links[side+'_stick'];root=e.links['controller_body'];direction=np.array([1.,0,0]) if side=='left' else np.array([-1.,0,0]);local=cap.entity_pose.to_transformation_matrix()[:3,:3].T@root.entity_pose.to_transformation_matrix()[:3,:3]@direction;plan=cap_point(cap,local);folder=out/(side+'_'+str(fv));save(folder/'point.json',plan);sink=ResultSink(folder/'trace.jsonl');rows=[]
   stages=[('settle',250),('ramp_up',125),('hold',250),('ramp_down',125),('observe',125)]
   try:
    for phase,count in stages:
     for i in range(count):
      factor=(i+1)/count if phase=='ramp_up' else 1-(i+1)/count if phase=='ramp_down' else 1 if phase=='hold' else 0
      rm=root.entity_pose.to_transformation_matrix();cm=cap.entity_pose.to_transformation_matrix();horizontal=rm[:3,:3]@direction;vertical=rm[:3,:3]@np.array([0,0,-1.]);force=factor*(horizontal+fv*vertical);point=cm[:3,:3]@plan['point_local_m']+cm[:3,3]
      if factor:cap.add_force_at_point(force,point,mode='force')
      e.scene.step();cm=cap.entity_pose.to_transformation_matrix();axis=cm[:3,2].astype(float);ref=rm[:3,2].astype(float);theta=math.degrees(math.acos(float(np.clip(axis@ref/np.linalg.norm(axis)/np.linalg.norm(ref),-1,1))));q=e.gamepad.joint_positions()[side+'_stick_click'];signal=e.gamepad.gamepad_state().channel(side+'_stick');row={'step':len(rows),'phase':phase,'phase_step':i,'angle_deg':theta,'q_m':q,'raw_fraction':q/.0004,'signal':signal,'force_world_n':force.tolist(),'horizontal_unit_world':horizontal.tolist(),'vertical_unit_world':vertical.tolist(),'application_point_world_m':point.tolist(),'cap_pose':[float(x) for x in (*cap.entity_pose.p,*cap.entity_pose.q)]};rows.append(row);sink.write(row)
   finally:sink.close()
   hold=[r for r in rows if r['phase']=='hold'];last=hold[-125:];valid=min(r['angle_deg'] for r in hold)>=1;low=max(r['signal'] for r in hold)<=.05 if fv<6.66 else None;positive=min(r['signal'] for r in last)>=.95 if fv==8.14 else None;returned=rows[-1]['signal']<=.05;result={'model':model,'side':side,'vertical_force_n':fv,'fixture_valid':valid,'hold_min_angle_deg':min(r['angle_deg'] for r in hold),'hold_max_angle_deg':max(r['angle_deg'] for r in hold),'hold_click_max':max(r['signal'] for r in hold),'hold_raw_max':max(r['raw_fraction'] for r in hold),'positive_control_final_hold_min':min(r['signal'] for r in last) if fv==8.14 else None,'low_force_pass':low,'positive_control_pass':positive,'unload_final_signal':rows[-1]['signal'],'unload_pass':returned,'physics_passed':bool((low if low is not None else positive) and returned) if valid else None,'status':'fixture_invalid' if not valid else 'passed' if (low if low is not None else positive) and returned else 'failed'};results.append(result);save(out/'results.json',{'protocol_id':p['protocol_id'],'results':results});print(json.dumps(result),flush=True)
 return results
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--model',choices=['new','main_73c8676'],required=True);a=p.parse_args();run(a.resources,a.output,a.model)
