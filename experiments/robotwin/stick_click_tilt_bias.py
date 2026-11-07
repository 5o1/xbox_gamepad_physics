"""Owner ruling8 one-factor diagnosis of tilted no-load click offset."""
import argparse,json,os,hashlib,math
from pathlib import Path
from unittest.mock import patch
import numpy as np
from tests.acceptance.robotwin.stick_click import setup,sample,save
from experiments.robotwin.joint_readback import policy
from tests.acceptance.records import ResultSink

HERE=Path(__file__).resolve().parent

def run(resources,out):
 os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(resources.resolve());out.mkdir(parents=True,exist_ok=True)
 p=HERE/'stick_click_tilt_bias_protocol.json';protocol=json.loads(p.read_text());save(out/'registration.json',{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'protocol':protocol})
 conditions=[(s,a,'baseline') for s in ['left','right'] for a in [0,12,20,23]]+[(s,20,n) for s in ['left','right'] for n in ['tilt_stiffness10','without_distance_constraint','without_preload','prismatic_upper4mm','sleep_disabled']]
 results=[]
 for side,angle,contrast in conditions:
  if contrast=='without_distance_constraint':
   with patch('xbox_gamepad_physics.robotwin.mappings.attach_shaft_limits',return_value=([],[])):e=setup(side,angle)
  else:e=setup(side,angle)
  click=e.joints[side+'_stick_click'];before=policy(e)
  if contrast=='tilt_stiffness10':
   for suffix in ['x','y']:
    j=e.joints[side+'_stick_'+suffix];j.set_drive_properties(10,j.damping,force_limit=j.force_limit,mode=j.drive_mode)
  elif contrast=='without_preload':
   qf=e.art.get_qf().copy();idx=[j.name for j in e.art.get_active_joints()].index(click.name);qf[idx]+=7.4;e.art.set_qf(qf)
  elif contrast=='prismatic_upper4mm':click.set_limits([[0,.004]])
  elif contrast=='sleep_disabled':e.art.set_sleep_threshold(0)
  folder=out/(side+'_'+str(angle)+'_'+contrast);save(folder/'setup.json',{'before':before,'after':policy(e),'initial':sample(e),'preload_qf':e.art.get_qf().tolist(),'shaft_mapping':getattr(e.gamepad,'_shaft_limit_mapping',[])})
  links=e.art.get_links();indices={name:links.index(e.joints[name].get_child_link()) for name in [click.name,side+'_stick_x',side+'_stick_y']};rows=[];sink=ResultSink(folder/'trace.jsonl')
  try:
   for i in range(1500):
    e.scene.step();incoming=e.art.get_link_incoming_joint_forces();row={**sample(e),'step':i,'time_after_settle_s':(i+1)*.004,'sleeping':e.cap.sleeping,'qvel_m_s':e.gamepad.joint_velocity(click.name),'incoming_joint_wrenches':{n:incoming[k].tolist() for n,k in indices.items()}}
    row['lower_distance_m']=row['q_m'];row['upper_distance_m']=float(click.get_limits()[0][1])-row['q_m'];sink.write(row);rows.append(row)
  finally:sink.close()
  steady=rows[-250:];r={'side':side,'angle_deg':angle,'contrast':contrast,'max_fraction':max(x['raw_fraction'] for x in rows),'final_fraction':rows[-1]['raw_fraction'],'steady_min':min(x['raw_fraction'] for x in steady),'steady_max':max(x['raw_fraction'] for x in steady),'final_q_m':rows[-1]['q_m'],'actual_angle_deg':rows[-1]['shaft_angle_deg'],'final_incoming_wrenches':rows[-1]['incoming_joint_wrenches'],'final_qvel_m_s':rows[-1]['qvel_m_s']};results.append(r);save(out/'results.json',{'results':results});print(json.dumps(r),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.resources,a.output)
