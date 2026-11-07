"""Full-model a2 cone/click freedom subsystem check, not frozen acceptance."""
import argparse,json,os,math
from pathlib import Path
from unittest.mock import patch
import numpy as np
from tests.acceptance.robotwin.executor import RobotwinPressExecutor
from tests.acceptance.robotwin.stick_click import save

def run(resources,out):
 import sapien
 os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(resources.resolve());out.mkdir(parents=True,exist_ok=True)
 save(out/'registration.json',{'scope':'a2 full geometry mapping diagnostic using the explicitly supplied resource configuration; outside T1-T4','resource_manifest':str((resources/'robotwin/full_controls/manifest.json').resolve()),'conditions':'left/right, with/without pure angular constraint; command both tilt axes2xcontract max; native12N inward force at stick pivot during1s load then1s release; no q/qvel writes','dt_s':.004,'thresholds':{'cone_max_deg':23.1,'control_exceeds_deg':23.1,'click_loaded_fraction_min':.95,'click_released_fraction_max':.05}})
 results=[]
 def cpu_scene(*,timestep,**kwargs):s=sapien.Scene([sapien.physx.PhysxCpuSystem()]);s.set_timestep(timestep);return s
 for side in ['left','right']:
  for enabled in [True,False]:
   e=RobotwinPressExecutor()
   with patch('tests.acceptance.robotwin.executor.create_scene',side_effect=cpu_scene):
    if enabled:e.setup([0,0,.03,1,0,0,0])
    else:
     with patch('xbox_gamepad_physics.robotwin.mappings.attach_shaft_limits',return_value=([],[])):e.setup([0,0,.03,1,0,0,0])
   cap=e.links[side+'_stick'];axes=[e.joints[side+'_stick_'+s] for s in ['x','y']]
   for _ in range(250):e.scene.step()
   limit=float(axes[0].get_limits()[0][1])
   for j in axes:j.set_drive_target(2*limit)
   rows=[];folder=out/(side+('_cone' if enabled else '_control'));folder.mkdir(parents=True,exist_ok=True)
   with (folder/'trace.jsonl').open('w') as stream:
    for i in range(500):
     if i==250:
      for j in axes:j.set_drive_target(0)
     if i<250:cap.add_force_at_point([0,0,-12],cap.entity_pose.p)
     e.scene.step();axis=cap.entity_pose.to_transformation_matrix()[:3,2].astype(float);theta=math.degrees(math.acos(float(np.clip(axis[2]/np.linalg.norm(axis),-1,1))));q=e.gamepad.joint_positions()[side+'_stick_click'];row={'step':i,'time_s':(i+1)*.004,'angle_deg':theta,'click_q_m':q,'raw_fraction':q/.0004,'signal':e.gamepad.gamepad_state().channel(side+'_stick')};rows.append(row);stream.write(json.dumps(row)+'\n')
   steady=rows[199:250];release=rows[449:500];r={'side':side,'cone':enabled,'loaded_angle_min':min(x['angle_deg'] for x in steady),'loaded_angle_max':max(x['angle_deg'] for x in steady),'loaded_click_min':min(x['raw_fraction'] for x in steady),'release_click_max':max(x['raw_fraction'] for x in release),'release_angle_max':max(x['angle_deg'] for x in release),'mapping':getattr(e.gamepad,'_shaft_limit_mapping',[])};r['subsystem_passed']=(r['loaded_angle_max']<=23.1 if enabled else r['loaded_angle_min']>23.1) and r['loaded_click_min']>=.95 and r['release_click_max']<=.05;results.append(r);save(out/'results.json',{'results':results});print(json.dumps(r),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.resources,a.output)
