"""Ruling8 timing-controlled repeat: overrides before the settling transient."""
import argparse,json,os
from pathlib import Path
from unittest.mock import patch
from tests.acceptance.robotwin.executor import RobotwinPressExecutor
from tests.acceptance.robotwin.stick_click import setup,sample,save
from experiments.robotwin.joint_readback import policy
from tests.acceptance.records import ResultSink

class TiltProxy:
 def __init__(self,native):self.native=native
 def __getattr__(self,name):return getattr(self.native,name)
 def set_drive_properties(self,stiffness,damping,**kwargs):return self.native.set_drive_properties(10,damping,**kwargs)

def run(resources,out):
 out.mkdir(parents=True,exist_ok=True);os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(resources.resolve())
 save(out/'registration.json',{'purpose':'Correct onset timing, not change parameter values or acceptance criteria. Original first batch preserved.','conditions':['tilt_stiffness10','without_preload','prismatic_upper4mm','sleep_disabled'],'sides':['left','right'],'angle_deg':20,'timing':'Apply override immediately after loading, before tilt drive setup and1s settling. K proxy forwards the original drive call changing only stiffness100->10.','dt_s':.004,'observed_steps':1500})
 original=RobotwinPressExecutor.setup;results=[]
 for side in ['left','right']:
  for condition in ['tilt_stiffness10','without_preload','prismatic_upper4mm','sleep_disabled']:
   captured={}
   def start(e,*args,**kwargs):
    original(e,*args,**kwargs);captured['before']=policy(e);click=e.joints[side+'_stick_click']
    if condition=='tilt_stiffness10':
     for suffix in ['x','y']:
      name=side+'_stick_'+suffix;e.joints[name]=TiltProxy(e.joints[name])
    elif condition=='without_preload':
     qf=e.art.get_qf().copy();idx=[j.name for j in e.art.get_active_joints()].index(click.name);qf[idx]+=7.4;e.art.set_qf(qf)
    elif condition=='prismatic_upper4mm':click.set_limits([[0,.004]])
    else:e.art.set_sleep_threshold(0)
   with patch.object(RobotwinPressExecutor,'setup',start):e=setup(side,20)
   name=side+'_'+condition;save(out/name/'setup.json',{'before':captured['before'],'after':policy(e),'post_settle':sample(e),'qf':e.art.get_qf().tolist()})
   sink=ResultSink(out/name/'trace.jsonl');rows=[]
   try:
    for i in range(1500):
     e.scene.step();row={**sample(e),'step':i,'sleeping':e.cap.sleeping,'qvel_m_s':e.gamepad.joint_velocity(side+'_stick_click')};rows.append(row);sink.write(row)
   finally:sink.close()
   r={'side':side,'condition':condition,'final_fraction':rows[-1]['raw_fraction'],'actual_angle_deg':rows[-1]['shaft_angle_deg'],'max_fraction':max(x['raw_fraction'] for x in rows)};results.append(r);save(out/'results.json',{'results':results});print(json.dumps(r),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.resources,a.output)
