"""Per-step native force/torque readback for the suspicious View equilibrium."""
import argparse,ctypes,json,os,hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np
from experiments.robotwin.station_rtf import probe_p
from experiments.robotwin.station_rtf.overrides import policy
from tests.acceptance import load_suite
from tests.acceptance.robotwin import executor,run_suite
from tests.acceptance.records import ResultSink

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--library',type=Path,required=True);p.add_argument('--resources',required=True);p.add_argument('--iterations',nargs=2,type=int,required=True);p.add_argument('--channel',choices=['point','generalized'],default='point');p.add_argument('--remove-velocity-limit',action='store_true');a=p.parse_args()
os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=a.resources
import sapien
sapien.physx.set_scene_config(cpu_workers=0,enable_tgs=True)
lib=ctypes.CDLL(str(a.library));read=lib.probe_force_readback;read.argtypes=[ctypes.c_size_t,ctypes.POINTER(ctypes.c_float)];read.restype=ctypes.c_int
a.output.mkdir(parents=True,exist_ok=False)
with policy(tuple(a.iterations)),patch.object(executor,'create_scene',side_effect=run_suite.cpu_scene):
 case=load_suite().case('View');e=executor.RobotwinPressExecutor();e.setup([*case.root_pose.position_m,*case.root_pose.orientation_wxyz],.004)
 velocity_before=float(e.joints['view_press'].get_max_velocity())
 if a.remove_velocity_limit:e.joints['view_press'].set_max_velocity(float(np.finfo(np.float32).max))
 info=probe_p.model(e,case);info.update(velocity_limit_before_m_s=velocity_before,velocity_limit_m_s=float(e.joints['view_press'].get_max_velocity()));probe_p.save(a.output/'input.json',info)
 link=e.links['view'];direction=np.array(info['direction_world']);local=np.array(info['point_local_m']);idx=[j.name for j in e.art.get_active_joints()].index('view_press')
 def native():
  output=(ctypes.c_float*9)();status=read(link._physx_pointer,output)
  return dict(status=status,force_n=list(output[:3]),torque_nm=list(output[3:6]),com_world_m=list(output[6:9]))
 base_qf=e.art.get_qf().copy()
 rows=[];sink=ResultSink(a.output/'trace.jsonl')
 try:
  for phase,count in [('settle',125),('ramp',125),('hold',125),('observe',125)]:
   for i in range(count):
    factor=(i+1)/count if phase=='ramp' else 1 if phase=='hold' else 0
    frame=link.pose.to_transformation_matrix();point=frame[:3,:3]@local+frame[:3,3];command=direction*info['applied_force_n']*factor
    before=native()
    if a.channel=='generalized':
     loads=base_qf.copy();loads[idx]+=float(command@np.array(info['axis_world']));e.art.set_qf(loads)
    elif factor:link.add_force_at_point(command,point,mode='force')
    after=native();delta=np.array(after['force_n'])-before['force_n'];expected_torque=np.cross(point-np.array(after['com_world_m']),command)
    e.scene.step();post=native();q=float(e.art.get_qpos()[idx]);v=float(e.art.get_qvel()[idx]);signal=e.gamepad.gamepad_state().channel('back')
    row=dict(channel=a.channel,qf_readback_n=float(e.art.get_qf()[idx]),step=len(rows),phase=phase,command_n=command.tolist(),point_world_m=point.tolist(),before=before,after=after,post_step=post,delta_force_n=delta.tolist(),force_error_norm_n=float(np.linalg.norm(delta-command)),expected_torque_nm=expected_torque.tolist(),torque_error_norm_nm=float(np.linalg.norm(np.array(after['torque_nm'])-before['torque_nm']-expected_torque)),press_projection_n=float(delta@direction),q_m=q,qvel_m_s=v,travel_m=info['coordinate_travel'],signal=signal,q_over_travel=q/info['coordinate_travel'],remaining_travel_m=info['coordinate_travel']-q,elastic_at_observed_q_n=info['K']*(q-info['drive_target']),contacts=probe_p.contacts(e))
    sink.write(row);rows.append(row)
 finally:sink.close()
 hold=[r for r in rows if r['phase']=='hold'];summary=dict(remove_velocity_limit=a.remove_velocity_limit,channel=a.channel,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),iterations=a.iterations,input=info,force_norm_range_n=[min(np.linalg.norm(r['delta_force_n']) for r in hold),max(np.linalg.norm(r['delta_force_n']) for r in hold)],press_projection_range_n=[min(r['press_projection_n'] for r in hold),max(r['press_projection_n'] for r in hold)],max_force_error_n=max(r['force_error_norm_n'] for r in rows),max_torque_error_nm=max(r['torque_error_norm_nm'] for r in rows),max_before_accumulator_n=max(np.linalg.norm(r['before']['force_n']) for r in rows),max_post_accumulator_n=max(np.linalg.norm(r['post_step']['force_n']) for r in rows),hold_q_range_m=[min(r['q_m'] for r in hold),max(r['q_m'] for r in hold)],hold_signal_range=[min(r['signal'] for r in hold),max(r['signal'] for r in hold)],max_hold_abs_qvel_m_s=max(abs(r['qvel_m_s']) for r in hold),mean_hold_elastic_n=float(np.mean([r['elastic_at_observed_q_n'] for r in hold])),hold_steps=len(hold),native_readback='Sc::VelocityMod linearPerSec*mass; torque from angularPerSec and world inertia; world COM read through public API')
 probe_p.save(a.output/'summary.json',summary);print(json.dumps(summary),flush=True)
