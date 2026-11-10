"""Point-force diagnostic and unchanged 4ms T4; CPU only, no model writes."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import time
from unittest.mock import patch
import numpy as np

from experiments.robotwin.station_rtf.overrides import policy
from tests.acceptance import load_suite
from tests.acceptance.records import ResultSink
from tests.acceptance.robotwin import executor, run_suite
from tests.acceptance.scoring import target_value, misfires, threshold

DIGITAL = ['A','B','X','Y','View','Menu','Guide','LB','RB','Dpad_up','Dpad_down','Dpad_left','Dpad_right','L3','R3','Pair']
FOCUS = ['View','Menu','Guide']


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False)+'\n')


def surface_point(link, direction, axis, pivot, case):
    """Ray hit on actual collision triangles; never a convex hull surrogate."""
    meshes=[]
    for si, shape in enumerate(link.get_collision_shapes()):
        transform=(link.pose*shape.local_pose).to_transformation_matrix()
        vertices=np.asarray(shape.get_vertices(),dtype=float)*np.asarray(shape.get_scale())
        vertices=vertices@transform[:3,:3].T+transform[:3,3]
        triangles=np.asarray(shape.get_triangles()).reshape(-1,3)
        meshes.append((si,vertices,triangles))
    all_vertices=np.concatenate([v for _,v,_ in meshes])
    center=(all_vertices.min(0)+all_vertices.max(0))/2
    if case.plan['kind']=='dpad':
        arm=np.cross(direction,axis);arm/=np.linalg.norm(arm)
        desired=pivot+case.plan['sign']*.008*arm
        center += desired-center-direction*np.dot(desired-center,direction)
    outward=-direction
    hits=[]
    for si,vertices,triangles in meshes:
        tri=vertices[triangles]
        edge1=tri[:,1]-tri[:,0];edge2=tri[:,2]-tri[:,0]
        h=np.cross(np.broadcast_to(outward,edge2.shape),edge2)
        determinant=np.einsum('ij,ij->i',edge1,h)
        valid=np.abs(determinant)>1e-15
        inv=np.zeros_like(determinant);inv[valid]=1/determinant[valid]
        s=center-tri[:,0]
        u=inv*np.einsum('ij,ij->i',s,h)
        q=np.cross(s,edge1)
        v=inv*np.einsum('j,ij->i',outward,q)
        t=inv*np.einsum('ij,ij->i',edge2,q)
        valid &= (u>=-1e-7)&(v>=-1e-7)&(u+v<=1+1e-7)
        for idx in np.flatnonzero(valid):
            hits.append((float(t[idx]),si,int(idx),float(u[idx]),float(v[idx])))
    if not hits:
        raise ValueError(f'{case.case_id}: center ray misses actual collision triangles')
    distance,si,ti,u,v=max(hits)
    world=center+distance*outward
    transform=link.pose.to_transformation_matrix()
    local=transform[:3,:3].T@(world-transform[:3,3])
    return dict(point_local_m=local.tolist(),point_world_m=world.tolist(),ray_center_world_m=center.tolist(),outward_world=outward.tolist(),shape_index=si,triangle_index=ti,barycentric_uv=[u,v],method='actual collision triangle ray; Dpad uses signed 8mm rocker arm')


def model(e, case):
    joint=e.joints[case.plan['joint']]
    frame=(joint.get_child_link().pose*joint.get_pose_in_child()).to_transformation_matrix()
    axis=frame[:3,0];pivot=frame[:3,3]
    direction=np.array(case.plan['direction'],dtype=float) if case.plan['kind']=='dpad' else axis.copy()
    direction/=np.linalg.norm(direction)
    point=surface_point(e.links[case.plan['link']],direction,axis,pivot,case)
    lo,hi=map(float,joint.get_limits()[0]);sign=case.plan['sign']
    end=hi if sign>0 else lo
    target=float(joint.get_drive_target()[0]);K=float(joint.stiffness)
    qf={j.name:float(f) for j,f in zip(e.art.get_active_joints(),e.art.get_qf())}[joint.name]
    arm=float(axis@np.cross(np.asarray(point['point_world_m'])-pivot,direction)) if case.plan['kind']=='dpad' else float(axis@direction)
    required=(K*(end-target)-qf)/arm
    if required<=0:
        raise ValueError(f'{case.case_id}: nonpositive full-travel force {required}')
    link=e.links[case.plan['link']];parent=joint.get_parent_link();child=joint.get_child_link()
    return dict(**point,joint=joint.name,link=link.name,axis_world=axis.tolist(),pivot_world_m=pivot.tolist(),direction_world=direction.tolist(),limits=[lo,hi],end_coordinate=end,coordinate_travel=abs(end),coordinate_unit='rad' if case.plan['kind']=='dpad' else 'm',K=K,D=float(joint.damping),drive_target=target,drive_cap=float(joint.force_limit),qf=qf,force_conversion_arm=arm,full_travel_elastic_preload_force_n=required,applied_force_n=min(16.,1.5*required),force_basis='quasistatic elastic + persistent qf, excluding gravity/damping/friction',frozen_direction=case.plan['direction'],frozen_direction_dot_axis=float(np.asarray(case.plan['direction'])@axis),drive_mode=str(joint.get_drive_mode()),link_linear_damping=float(link.linear_damping),link_angular_damping=float(link.angular_damping),mass_kg=float(link.mass),inertia_kg_m2=link.inertia.tolist(),parent=parent.name,parent_mass_kg=float(parent.mass),child=child.name,child_mass_kg=float(child.mass),parent_child_mass_ratio=float(parent.mass/child.mass),iterations=[e.art.get_solver_position_iterations(),e.art.get_solver_velocity_iterations()])


def contacts(e):
    result=[]
    for c in e.scene.get_contacts():
        result.append(dict(bodies=[b.entity.name for b in c.bodies],points=[dict(position_m=p.position.tolist(),normal=p.normal.tolist(),impulse_ns=p.impulse.tolist(),separation_m=float(p.separation)) for p in c.points]))
    return result


def score(rows, case, dt, diagnostic_threshold=.95):
    hold=[r for r in rows if r['phase']=='hold'][-round(.5/dt):]
    observe=[r for r in rows if r['phase']=='observe']
    values=[r['target'] for r in hold]
    neutral=next((i for i,r in enumerate(observe) if all(abs(x['target'])<=1e-4 for x in observe[i:])),None)
    returned=None if neutral is None else neutral*dt
    criteria=load_suite().criteria
    bad={n:max(abs(r['signals'][n]) for r in hold) for n in hold[0]['signals'] if any(n in misfires(case.plan,r['signals'],criteria) for r in hold)}
    reached=min(values)>=diagnostic_threshold
    return dict(target_min=min(values),target_max=max(values),target_threshold=diagnostic_threshold,signal_passed=reached,misfires=bad,return_time_s=returned,return_passed=returned is not None and returned<=.5,passed=bool(reached and not bad and returned is not None and returned<=.5),max_joint_displacement=max(r['signed_q'] for r in rows),max_travel_fraction=max(r['travel_fraction'] for r in rows),contact_pairs=sorted({'/'.join(sorted(c['bodies'])) for r in rows for c in r['contacts']}),hold_samples=len(hold),observe_samples=len(observe))


def point_case(case,dt,out,native_read=None):
    import sapien
    e=executor.RobotwinPressExecutor()
    e.setup([*case.root_pose.position_m,*case.root_pose.orientation_wxyz],dt)
    info=model(e,case);save(out/'input.json',info)
    link=e.links[info['link']];direction=np.array(info['direction_world']);local=np.array(info['point_local_m'])
    rows=[];sink=ResultSink(out/'trace.jsonl')
    try:
        for phase,duration in [('settle',.5),('ramp',.5),('hold',.5),('observe',.5)]:
            for i in range(round(duration/dt)):
                factor=(i+1)/round(duration/dt) if phase=='ramp' else 1 if phase=='hold' else 0
                matrix=link.pose.to_transformation_matrix();point=matrix[:3,:3]@local+matrix[:3,3]
                force=direction*info['applied_force_n']*factor
                before=native_read(link) if native_read else None
                if factor:link.add_force_at_point(force,point,mode='force')
                after=native_read(link) if native_read else None
                e.scene.step()
                post=native_read(link) if native_read else None
                q=e.gamepad.joint_positions()[info['joint']];signed=case.plan['sign']*q
                signals=e.gamepad.gamepad_state().as_dict();events=e.gamepad.physical_events()
                row=dict(step=len(rows),time_s=(len(rows)+1)*dt,phase=phase,phase_time_s=i*dt,target=target_value(case.plan,signals,events),signals=signals,events=events,q=q,signed_q=signed,travel_fraction=signed/info['coordinate_travel'],force_world_n=force.tolist(),point_world_m=point.tolist(),contacts=contacts(e))
                if native_read:
                    delta=np.array(after['force_n'])-before['force_n']
                    row.update(native_force_before=before,native_force_after=after,native_force_post_step=post,native_force_delta_n=delta.tolist(),native_force_error_n=float(np.linalg.norm(delta-force)),native_expected_torque_nm=np.cross(point-np.array(after['com_world_m']),force).tolist(),qvel=e.art.get_qvel().tolist())
                sink.write(row);rows.append(row)
    finally:sink.close()
    audit=None
    if native_read:
        hold=[r for r in rows if r['phase']=='hold']
        audit=dict(max_force_error_n=max(r['native_force_error_n'] for r in rows),max_before_force_n=max(float(np.linalg.norm(r['native_force_before']['force_n'])) for r in rows),max_post_force_n=max(float(np.linalg.norm(r['native_force_post_step']['force_n'])) for r in rows),hold_force_norm_range_n=[min(float(np.linalg.norm(r['native_force_delta_n'])) for r in hold),max(float(np.linalg.norm(r['native_force_delta_n'])) for r in hold)],applied_hold_steps=int(sum(np.linalg.norm(r['native_force_delta_n'])>0 for r in hold)),hold_steps=len(hold))
    result=dict(native_force_audit=audit,case=case.case_id,method='P',dt_s=dt,model=info,termination='prescribed_force_then_unload',**score(rows,case,dt))
    save(out/'result.json',result)
    return result


def summarize_t4(out,case,dt):
    result=next(r for r in json.loads((out/'results.json').read_text())['results'] if r['case']==case.case_id)
    rows=[json.loads(line) for line in (out/case.case_id/'trace.jsonl').read_text().splitlines()]
    j=case.plan['joint'];travel=max(abs(v) for v in case.joint_limits[j])
    # Use actual current limits rather than the frozen ABXY artist travel.
    return dict(case=case.case_id,method='T4',dt_s=dt,target_min=result['target_min'],target_max=result['target_max'],passed=result['physics_passed'],target_threshold=result['target_threshold'],misfires=result['misfires'],return_time_s=result['return_time_after_withdraw_s'],termination=result['termination'],contact_pairs=sorted({'/'.join(sorted(c['bodies'])) for r in rows for c in r['contacts']}),max_joint_displacement=max(case.plan['sign']*r['joints'][j] for r in rows),frozen_joint_travel=travel,raw_result=result)


def t4_dt1(case,out):
    """Time-resampled diagnostic; original 4ms acceptance remains unchanged."""
    from tests.acceptance.runner import PressTrajectory,PressStop,ball_force
    from dataclasses import replace
    suite=load_suite();dt=.001
    fixture=dict(suite.fixture);fixture['dt_s']=dt
    suite=replace(suite,fixture=fixture)
    e=executor.RobotwinPressExecutor();e.reset_case(suite,case)
    trajectory=PressTrajectory(suite,case);trajectory.dt=dt
    trajectory.stop=PressStop(suite.settings,suite.press_stop,dt)
    rows=[];sink=ResultSink(out/'trace.jsonl')
    try:
        for i in range(40000):
            target=trajectory.before_step(i);state=e.ball_state()
            force=ball_force(suite.settings,target,state['position_m'],state['velocity_m_s'],suite.fixture['gravity_m_s2'])
            e.apply_ball_force(force);e.step(dt);row=e.sample()
            trajectory.after_step(i,target_value(case.plan,row['signals'],row['probe']['events']),row['probe']['pose'][:3],force)
            row.update(step=i,time_s=(i+1)*dt,phase=trajectory.phase,target=target_value(case.plan,row['signals'],row['probe']['events']),signed_q=case.plan['sign']*row['joints'][case.plan['joint']])
            row['probe'].update(phase=trajectory.phase,target_m=list(target),force_n=list(force),termination=trajectory.termination)
            limits=e.joints[case.plan['joint']].get_limits()[0];travel=max(abs(float(v)) for v in limits);row['travel_fraction']=row['signed_q']/travel
            sink.write(row);rows.append(row)
            if trajectory.phase=='done':break
        else:raise RuntimeError('resampled T4 exceeded explicit step budget')
    finally:sink.close()
    r=dict(case=case.case_id,method='T4_dt1_diagnostic',dt_s=dt,termination=trajectory.termination,**score(rows,case,dt))
    save(out/'result.json',r);return r


def main():
    import sapien
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--resources',type=Path,required=True);p.add_argument('--iterations',nargs=2,type=int,required=True);p.add_argument('--dt',type=float,choices=[.004,.001],default=.004);p.add_argument('--case',action='append',dest='cases');p.add_argument('--method',choices=['P','T4','both'],default='both');p.add_argument('--force-readback',type=Path);a=p.parse_args()
    os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(a.resources.resolve())
    sapien.physx.set_scene_config(cpu_workers=0,enable_tgs=True)
    native_read=None
    if a.force_readback:
        lib=ctypes.CDLL(str(a.force_readback));read=lib.probe_force_readback
        read.argtypes=[ctypes.c_size_t,ctypes.POINTER(ctypes.c_float)];read.restype=ctypes.c_int
        def native_read(link):
            values=(ctypes.c_float*9)();status=read(link._physx_pointer,values)
            return dict(status=status,force_n=list(values[:3]),torque_nm=list(values[3:6]),com_world_m=list(values[6:9]))
    a.output.mkdir(parents=True,exist_ok=False)
    suite=load_suite();cases=a.cases or (FOCUS if a.dt==.001 else DIGITAL)
    summary=dict(iterations=a.iterations,dt_s=a.dt,results=[],versions={n:importlib.metadata.version(n) for n in ['sapien','xbox-gamepad-physics']},resources=str(a.resources),cpu_affinity=sorted(os.sched_getaffinity(0)),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),frozen_protocol_sha256=hashlib.sha256(Path('tests/acceptance/data/ruling20_sdf303_v1.json').read_bytes()).hexdigest(),native_force_readback_library_sha256=hashlib.sha256(a.force_readback.read_bytes()).hexdigest() if a.force_readback else None,sphere_iterations_policy='T4 sphere retains frozen native default; actual readback in input_receipt',started=time.time())
    with policy(tuple(a.iterations)),patch.object(executor,'create_scene',side_effect=run_suite.cpu_scene):
        if a.method in ['P','both']:
            for name in cases:
                result=point_case(suite.case(name),a.dt,a.output/'P'/name,native_read)
                summary['results'].append(result);save(a.output/'summary.json',summary)
                print(json.dumps({k:v for k,v in result.items() if k!='model'}),flush=True)
        if a.method in ['T4','both']:
            if a.dt==.004:
                run_suite.run(a.resources,a.output/'T4',cases=cases,collect_all=True)
                for name in cases:
                    result=summarize_t4(a.output/'T4',suite.case(name),a.dt)
                    info=json.loads((a.output/'P'/name/'input.json').read_text()) if (a.output/'P'/name/'input.json').exists() else None
                    if info:result.update(max_travel_fraction=result['max_joint_displacement']/info['coordinate_travel'])
                    summary['results'].append(result)
            else:
                for name in cases:summary['results'].append(t4_dt1(suite.case(name),a.output/'T4_dt1_diagnostic'/name))
    summary['elapsed_s']=time.time()-summary['started'];summary['completed']=True
    save(a.output/'summary.json',summary)
    print(json.dumps(dict(completed=True,elapsed_s=summary['elapsed_s'],count=len(summary['results']))),flush=True)

if __name__=='__main__':main()
