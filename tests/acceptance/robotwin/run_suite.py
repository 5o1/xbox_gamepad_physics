"""Run existing frozen executor with an explicit CPU-only scene and snapshot."""
import argparse,json,os
from pathlib import Path
from unittest.mock import patch
from tests.acceptance.robotwin import executor

def cpu_scene(*,timestep,**kwargs):
 import sapien
 scene=sapien.Scene([sapien.physx.PhysxCpuSystem()]);scene.set_timestep(timestep);return scene

def run(resources,out,cases=None,iterations=None,idle_steps=0,collect_all=False,*,suite=None):
 import sapien
 from importlib.metadata import version
 os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(resources.resolve())
 import hashlib,numpy as np
 from tests.acceptance.runner import ball_force
 original_reset=executor.RobotwinPressExecutor.reset_case
 receipts=[]
 def observed_reset(e,suite,case):
  original_reset(e,suite,case)
  before=[e.art.get_solver_position_iterations(),e.art.get_solver_velocity_iterations(),e.ball.get_solver_position_iterations(),e.ball.get_solver_velocity_iterations()]
  if iterations:
   for body in [e.art,e.ball]:
    body.set_solver_position_iterations(iterations[0]);body.set_solver_velocity_iterations(iterations[1])
  flags=e.scene.physx_system.config
  rec={'case':case.case_id,'root_pose':[float(x) for x in (*e.art.get_root_pose().p,*e.art.get_root_pose().q)],'iterations_before':before,'art_iterations':[e.art.get_solver_position_iterations(),e.art.get_solver_velocity_iterations()],'ball_iterations':[e.ball.get_solver_position_iterations(),e.ball.get_solver_velocity_iterations()],'scene_flags':{k:getattr(flags,k) for k in ['enable_tgs','enable_pcm','enable_ccd','enable_enhanced_determinism','enable_friction_every_iteration']},'gravity':flags.gravity.tolist(),'dt':e.scene.get_timestep(),'sphere_mass':e.ball.mass,'sphere_inertia':e.ball.inertia.tolist(),'frozen_settings':dict(suite.settings),'frozen_fixture':dict(suite.fixture),'plan':dict(case.plan),'idle_steps':idle_steps,'joints':{j.name:{'K':j.stiffness,'D':j.damping,'target':j.get_drive_target().tolist(),'friction':j.get_friction(),'effort':j.force_limit} for j in e.art.get_active_joints()}}
  target=np.asarray(case.plan['start_m'])-np.asarray(case.plan['direction'])*.015
  for _ in range(idle_steps):
   state=e.ball_state();force=ball_force(suite.settings,target,state['position_m'],state['velocity_m_s'],suite.fixture['gravity_m_s2']);e.apply_ball_force(force);e.scene.step()
  rec['post_idle_probe']=e.ball_state();rec['post_idle_q']=e.gamepad.joint_positions();receipts.append(rec)
 with patch.object(executor,'create_scene',side_effect=cpu_scene),patch.object(executor.RobotwinPressExecutor,'reset_case',observed_reset):result=executor.execute_suite(out,case_ids=cases,stop_on_regression=not collect_all,suite=suite)
 receipt={'sapien':version('sapien'),'resources':str(resources.resolve()),'scene':'CPU-only, no renderer','selected_cases':cases,'collect_all_diagnostic_records':collect_all,'summary':result['summary'],'regressions':result['regressions']}
 (out/'runtime.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
 manifest=json.loads((resources/'robotwin/full_controls/manifest.json').read_text());paths=[resources/'robotwin/full_controls'/p for p in manifest['required_files']]+[resources/'robotwin/full_controls/manifest.json',resources/manifest['motion_contract'],Path(__file__),Path(executor.__file__),Path(__file__).parent.parent/'data/ruling20_sdf303_v1.json']
 (out/'input_receipt.json').write_text(json.dumps({'cases':receipts,'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
 return bool(result['regressions'])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--case',action='append',dest='cases');p.add_argument('--diagnostic-iterations',nargs=2,type=int);p.add_argument('--diagnostic-idle-steps',type=int,default=0);p.add_argument('--collect-all',action='store_true',help='Archive every frozen result without hiding any regression; candidate fails if any original pass regresses.');a=p.parse_args();raise SystemExit(run(a.resources,a.output,a.cases,a.diagnostic_iterations,a.diagnostic_idle_steps,a.collect_all))
