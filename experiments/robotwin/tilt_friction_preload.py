"""Ruling12 factor controls using the exact production cone experiment."""
import argparse,json,hashlib,os
from pathlib import Path
from unittest.mock import patch
from tests.acceptance.robotwin import stick_cone_production as cone
from tests.acceptance.robotwin.executor import RobotwinPressExecutor
from tests.acceptance.robotwin.stick_click import save
from experiments.robotwin.joint_readback import policy
from tests.acceptance.records import ResultSink

P=Path(__file__).with_name('tilt_friction_preload_protocol.json')
def run(new,old,out):
 out.mkdir(parents=True,exist_ok=True);save(out/'registration.json',{'protocol':json.loads(P.read_text()),'sha256':hashlib.sha256(P.read_bytes()).hexdigest()})
 original_setup=cone.setup;original_load=RobotwinPressExecutor.setup;overall=[]
 for variant in ['new_baseline','tilt_friction_zero','click_preload_zero','click_preload_0p111','main_73c8676']:
  os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(old if variant=='main_73c8676' else new);counter=[0];sinks=[]
  def make(side,hold=False):
   direction=['diagonal45','positive_x','positive_y'][counter[0]%3];counter[0]+=1;folder=out/variant/(side+'_'+direction);sink=ResultSink(folder/'wrench_trace.jsonl');sinks.append(sink);step_counter=[0]
   def loaded(e,*args,**kwargs):
    original_load(e,*args,**kwargs);before=policy(e);qf_before=e.art.get_qf().copy()
    if variant=='tilt_friction_zero':
     for suffix in ['x','y']:e.joints[side+'_stick_'+suffix].set_friction(0)
    elif variant in ['click_preload_zero','click_preload_0p111']:
     qf=e.art.get_qf().copy();idx=[j.name for j in e.art.get_active_joints()].index(side+'_stick_click');qf[idx]=0 if variant=='click_preload_zero' else -.111;e.art.set_qf(qf)
    save(folder/'factor_readback.json',{'before':before,'after':policy(e),'qf_before':qf_before.tolist(),'qf_after':e.art.get_qf().tolist(),'physics_system':type(e.scene.physx_system).__name__,'gravity':e.scene.physx_system.config.gravity.tolist(),'dt_s':e.scene.get_timestep()})
    actual=e.scene.step;links=e.art.get_links();names=[side+'_stick_x',side+'_stick_y'];indices={n:links.index(e.joints[n].get_child_link()) for n in names}
    def observed_step():
     actual();w=e.art.get_link_incoming_joint_forces();row={'step_including_settle':step_counter[0],'time_s':(step_counter[0]+1)*.004,'q':e.gamepad.joint_positions(),'qvel':[float(v) for v in e.art.get_qvel()],'tilt_incoming_joint_wrenches':{n:w[idx].tolist() for n,idx in indices.items()}};sink.write(row);step_counter[0]+=1
    e.scene.step=observed_step
   with patch.object(RobotwinPressExecutor,'setup',loaded):return original_setup(side,hold=hold)
  try:
   with patch.object(cone,'setup',make):cone.run(out/variant)
  finally:
   for sink in sinks:sink.close()
  results=json.loads((out/variant/'results.json').read_text());overall.append({'variant':variant,'results':results});save(out/'results.json',{'variants':overall})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--new',type=Path,required=True);p.add_argument('--old',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.new.resolve(),a.old.resolve(),a.output.resolve())
