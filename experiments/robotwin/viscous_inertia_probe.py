"""Known external torque controls for the small-inertia viscous anomaly."""
import argparse,importlib.util,inspect,json,hashlib
from pathlib import Path
import numpy as np

def run(source,out):
 out.mkdir(parents=True,exist_ok=True);protocol={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'purpose':'Separate effective inertia response from viscous friction response. No new candidate fitting.','inertias':[1e-4,8e-7],'solver':['PGS','TGS'],'dt':.004,'external_torque_Nm':1e-6,'steps':1,'new_friction':[0,0,0],'build_time_inertia':True};(out/'registration.json').write_text(json.dumps(protocol,indent=2)+'\n')
 spec=importlib.util.spec_from_file_location('minimal',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);results=[]
 for tgs in [False,True]:
  for I in [1e-4,8e-7]:
   text=inspect.getsource(module.fixture).replace('rod.set_mass_and_inertia(.01, sapien.Pose(), [1e-4]*3)','rod.set_mass_and_inertia(.01, sapien.Pose(), [requested_inertia]*3)');scope=dict(module.__dict__);scope['requested_inertia']=I;exec(compile(text,'<same fixture, explicit inertia>','exec'),scope);scene,art,j=scope['fixture']('new',0,.004,tgs);j.set_friction(0);j.set_friction_params(0,0,0);j.set_drive_properties(0,0);art.set_qpos([0,0]);art.set_qvel([0,0]);art.set_qf([0,1e-6]);before=art.get_qvel().tolist();scene.step();after=art.get_qvel().tolist();r={'TGS':tgs,'inertia_readback':j.child_link.inertia.tolist(),'mass':j.child_link.mass,'cmass_pose':j.child_link.cmass_local_pose.to_transformation_matrix().tolist(),'before_qvel':before,'after_qvel':after,'qf':art.get_qf().tolist(),'expected_delta_velocity':1e-6*.004/I,'measured_effective_I':1e-6*.004/(after[1]-before[1]) if after[1]!=before[1] else None,'legacy':j.get_friction(),'new_params':j.get_friction_params().tolist(),'max_joint_velocity':j.get_max_velocity(),'armature':j.get_armature().tolist()};results.append(r)
 (out/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.source,a.output)
