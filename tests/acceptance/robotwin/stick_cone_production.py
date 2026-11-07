"""Frozen production-parameter native shaft-limit experiment."""
import argparse,json,hashlib,math
from pathlib import Path
import numpy as np
from tests.acceptance.records import ResultSink
P=Path(__file__).with_name('stick_cone_production_protocol.json')

def score_trace(direction, rows, protocol):
 """Apply the written angular criteria; reaching the boundary is diagnostic."""
 steady_start,steady_end=protocol['steady_window_s']
 release_start,_=protocol['release_window_s']
 hold=[r for r in rows if steady_start-1e-9<=r['time_s']<=steady_end+1e-9]
 release=[r for r in rows if r['time_s']>=release_start-1e-9]
 loaded=[r for r in rows if r['time_s']<=protocol['load_s']+1e-9]
 criteria=protocol['criteria']
 first=next((r for a,r,b in zip(loaded,loaded[1:],loaded[2:]) if r['angle_deg']>a['angle_deg'] and b['angle_deg']<=r['angle_deg']),None)
 lower=min(r['angle_deg'] for r in hold)
 upper=max(r['angle_deg'] for r in hold)
 boundary=lower>=criteria['single_axis_min_deg']
 upper_pass=upper<=criteria['diagonal_max_deg' if direction=='diagonal45' else 'single_axis_max_deg']
 release_angle=max(r['angle_deg'] for r in release)
 release_speed=max(abs(v) for r in release for v in r['tilt_qvel_rad_s'])
 returned=release_angle<=criteria['release_max_deg'] and release_speed<=criteria['release_joint_speed_max_rad_s']
 return {'direction':direction,'steady_min_deg':lower,'steady_max_deg':upper,
         'first_peak_deg':first['angle_deg'] if first else None,'first_peak_time_s':first['time_s'] if first else None,
         'load_peak_deg':max(r['angle_deg'] for r in loaded),'release_max_deg':release_angle,
         'release_max_speed_rad_s':release_speed,'boundary_reached':boundary,
         'upper_bound_pass':upper_pass,'return_pass':returned,
         'passed':upper_pass and returned and (direction=='diagonal45' or boundary)}

def run(out,cases=None):
 from tests.acceptance.robotwin.stick_click import setup,save
 p=json.loads(P.read_text());out.mkdir(parents=True,exist_ok=True);save(out/'registration.json',{'protocol':p,'sha256':hashlib.sha256(P.read_bytes()).hexdigest()});results=[]
 for side in p['sides']:
  for name,vector in [('diagonal45',[2**-.5,2**-.5,0]),('positive_x',[1,0,0]),('positive_y',[0,1,0])]:
   if cases is not None and (side,name) not in cases:continue
   e=setup(side,hold=False);cap=e.cap;folder=out/(side+'_'+name);sink=ResultSink(folder/'trace.jsonl');rows=[]
   save(folder/'policy.json',{'joints':{n:{'K':j.stiffness,'D':j.damping,'friction':j.get_friction(),'velocity':j.get_max_velocity(),'target':j.get_drive_target().tolist(),'effort':j.force_limit} for n,j in e.joints.items()},'qf':e.art.get_qf().tolist()})
   try:
    for i in range(500):
     t=(i+1)*.004;matrix=cap.entity_pose.to_transformation_matrix();point=matrix[:3,3]+matrix[:3,:3]@np.array([0,0,.017914746775954664]);force=np.array(vector)*p['force_n'] if i<250 else np.zeros(3)
     if i<250:cap.add_force_at_point(force,point)
     e.scene.step();axis=cap.entity_pose.to_transformation_matrix()[:3,2].astype(float);ref=e.links['controller_body'].entity_pose.to_transformation_matrix()[:3,2].astype(float);theta=math.degrees(math.acos(float(np.clip(axis@ref/np.linalg.norm(axis)/np.linalg.norm(ref),-1,1))))
     row={'time_s':t,'angle_deg':theta,'tilt_qvel_rad_s':[e.gamepad.joint_velocity(side+'_stick_'+s) for s in ['x','y']],'q':e.gamepad.joint_positions(),'force_world_n':force.tolist(),'point_world_m':point.tolist()};rows.append(row);sink.write(row)
   finally:sink.close()
   result={'side':side,**score_trace(name,rows,p)}
   results.append(result);save(out/'results.json',{'results':results,'passed':all(r['passed'] for r in results)});print(json.dumps(result),flush=True)
 return all(r['passed'] for r in results)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();raise SystemExit(not run(a.output))
