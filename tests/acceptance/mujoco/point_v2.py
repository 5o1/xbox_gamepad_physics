"""Native MuJoCo execution of the owner-approved moving-point T3 v2."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import mujoco as mj
import numpy as np
from tests.acceptance import load_suite
from xbox_gamepad_physics.mujoco.loader import make_spec
from xbox_gamepad_physics.mujoco.numerics import apply_standalone_policy

PROTOCOL_PATH=Path(__file__).with_name('stick_click_t3_point_v2.json')
P=json.loads(PROTOCOL_PATH.read_text())

def save(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')

def cap_geometry(model,data,side):
    """Use the highest actual shell as thumbpad, excluding the lower dome."""
    body=model.body(side+'_stick').id;root=model.body('controller_body').id
    root_R=data.xmat[root].reshape(3,3);cap_R=data.xmat[body].reshape(3,3)
    shells=[]
    for gid in range(model.ngeom):
        if model.geom_bodyid[gid]!=body:continue
        mid=model.geom_dataid[gid]
        if mid<0:continue
        va,vn=model.mesh_vertadr[mid],model.mesh_vertnum[mid]
        fa,fn=model.mesh_faceadr[mid],model.mesh_facenum[mid]
        world=model.mesh_vert[va:va+vn]@data.geom_xmat[gid].reshape(3,3).T+data.geom_xpos[gid]
        shell_vertices=(world-data.xpos[root])@root_R
        shell_triangles=shell_vertices[model.mesh_face[fa:fa+fn]]
        lower,upper=shell_vertices.min(0),shell_vertices.max(0)
        shells.append({'geom':model.geom(gid).name,'triangles':shell_triangles,
                       'lower':lower,'upper':upper,'vertices':int(vn),'faces':int(fn)})
    if not shells:raise ValueError('Stick has no actual cap mesh shells')
    thumbpad=max(shells,key=lambda shell:float(shell['upper'][2]))
    triangles=thumbpad['triangles']
    lower,upper=thumbpad['lower'],thumbpad['upper']
    center=(lower+upper)/2
    radius=(upper[0]-lower[0])/2
    target=center[:2].copy();target[0]+=(1 if side=='left' else -1)*P['point']['radial_fraction']*radius
    # Project onto the selected upper thumbpad, not the lower dome/stem shell.
    a=triangles[:,0,:2];u=triangles[:,1,:2]-a;v=triangles[:,2,:2]-a;w=target-a
    det=u[:,0]*v[:,1]-u[:,1]*v[:,0]
    good=np.abs(det)>1e-16
    b=np.zeros(len(det));c=b.copy()
    b[good]=(w[good,0]*v[good,1]-w[good,1]*v[good,0])/det[good]
    c[good]=(u[good,0]*w[good,1]-u[good,1]*w[good,0])/det[good]
    inside=good&(b>=-1e-10)&(c>=-1e-10)&(b+c<=1+1e-10)
    if not inside.any():raise ValueError('Requested half-radius point misses actual upper thumbpad triangles')
    z=triangles[:,0,2]+b*(triangles[:,1,2]-triangles[:,0,2])+c*(triangles[:,2,2]-triangles[:,0,2])
    point_shell=np.array([*target,float(z[inside].max())])
    point_world=data.xpos[root]+root_R@point_shell
    local=cap_R.T@(point_world-data.xpos[body])
    all_triangles=np.concatenate([shell['triangles'] for shell in shells])
    whole_lower=all_triangles.reshape(-1,3).min(0);whole_upper=all_triangles.reshape(-1,3).max(0)
    local_tri=(all_triangles@root_R.T+data.xpos[root]-data.xpos[body])@cap_R
    records=[{'geom':shell['geom'],'bbox_shell_m':[shell['lower'].tolist(),shell['upper'].tolist()],
              'directional_radius_x_m':float((shell['upper'][0]-shell['lower'][0])/2),
              'vertices':shell['vertices'],'faces':shell['faces']} for shell in shells]
    return local,{'point_local_m':local.tolist(),'point_shell_neutral_m':point_shell.tolist(),
        'cap_center_xy_shell_m':center[:2].tolist(),'directional_radius_m':float(radius),
        'selected_cap_geom':thumbpad['geom'],'shell_bbox_m':[lower.tolist(),upper.tolist()],
        'whole_link_directional_radius_m':float((whole_upper[0]-whole_lower[0])/2),
        'whole_link_bbox_m':[whole_lower.tolist(),whole_upper.tolist()],
        'actual_shells':records,'triangles_local_m':local_tri.tolist(),
        'geometry_method':P['point']['geometry_method'],'root_rotation_world':root_R.tolist(),
        'stick_rotation_neutral_world':cap_R.tolist()}

def run(resources,output,label):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    save(output/'registration.json',{'protocol_sha256':hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
        'protocol':P,'executor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'resources':str(Path(resources).resolve()),'label':label,'native_api':'mj_applyFT at moving stick material point, force held/recomputed every physical substep'})
    asset=make_spec(resource_root=resources,fixed_root=True,pose=load_suite().case('L3').root_pose,attach_visual=False)
    apply_standalone_policy(asset.spec.option,asset.numerical_policy)
    asset.spec.option.gravity=P['gravity_m_s2']
    asset.spec.option.sdf_iterations=asset.sdf_policy['sdf_iterations'];asset.spec.option.sdf_initpoints=asset.sdf_policy['sdf_initpoints']
    model=asset.spec.compile();dt=float(model.opt.timestep)
    if dt!=P['physics_timestep_s']:raise ValueError('Physical dt differs from registered0.5ms')
    geometry={}
    neutral=mj.MjData(model);asset.bind(model,neutral);mj.mj_forward(model,neutral)
    for side in ('left','right'):
        local,record=cap_geometry(model,neutral,side);geometry[side]=record
    save(output/'geometry.json',geometry)
    results=[{'side':side,'vertical_force_n':fv,'status':'not_run','fixture_valid':None,'physics_passed':None}
             for side in ('left','right') for fv in P['vertical_forces_n']]
    completed=0;timing=P['timing_s'];start=timing['settle'];hold_start=start+timing['ramp_up'];unload_start=hold_start+timing['hold'];observe_start=unload_start+timing['ramp_down'];end=observe_start+timing['observe']
    for side in ('left','right'):
        for fv in P['vertical_forces_n']:
            data=mj.MjData(model);handle=asset.bind(model,data);mj.mj_forward(model,data)
            body=model.body(side+'_stick').id;root=model.body('controller_body').id
            point=np.array(geometry[side]['point_local_m']);rows=[]
            path=output/f'{side}_{fv:g}N';path.mkdir(exist_ok=True)
            with gzip.open(path/'trace.jsonl.gz','wt',compresslevel=1) as sink:
                for i in range(round(end/dt)):
                    t=(i+1)*dt
                    factor=0. if t<=start or t>observe_start else ((t-start)/timing['ramp_up'] if t<=hold_start else (1. if t<=unload_start else (observe_start-t)/timing['ramp_down']))
                    root_R=data.xmat[root].reshape(3,3);cap_R=data.xmat[body].reshape(3,3)
                    force=root_R@(factor*(np.asarray(P['push_directions_shell'][side])*P['horizontal_force_n']+np.asarray(P['vertical_direction_shell'])*fv))
                    applied_point=data.xpos[body]+cap_R@point
                    data.qfrc_applied[:]=0
                    mj.mj_applyFT(model,data,force,np.zeros(3),applied_point,body,data.qfrc_applied)
                    mj.mj_step(model,data)
                    if any(w.number for w in data.warning) or not np.isfinite(data.qpos).all():raise RuntimeError(f'Native warning/nonfinite at {side}/{fv}/{t}')
                    mj.mj_forward(model,data)
                    shaft=data.xmat[body].reshape(3,3)[:,2];reference=data.xmat[root].reshape(3,3)[:,2]
                    angle=math.degrees(math.atan2(np.linalg.norm(np.cross(shaft,reference)),shaft@reference))
                    q=handle.joint_position(side+'_stick_click');signal=handle.gamepad_state().channel(side+'_stick')
                    row={'time_s':t,'phase':'settle' if t<=start else ('ramp_up' if t<=hold_start else ('hold' if t<=unload_start else ('ramp_down' if t<=observe_start else 'observe'))),
                        'q_m':q,'raw_fraction':q/P['travel_m'],'signal':signal,'tilt_deg':angle,
                        'force_world_n':force.tolist(),'point_world_applied_m':applied_point.tolist(),
                        'point_world_post_m':(data.xpos[body]+data.xmat[body].reshape(3,3)@point).tolist(),
                        'shaft_world':shaft.tolist(),'q':data.qpos.tolist(),'qvel':data.qvel.tolist(),'qacc':data.qacc.tolist(),
                        'actuator_force':data.actuator_force.tolist(),'ncon':int(data.ncon)}
                    rows.append(row);sink.write(json.dumps(row)+'\n')
            hold=[r for r in rows if r['phase']=='hold'];last=[r for r in hold if r['time_s']>unload_start-P['criteria']['positive_last_hold_window_s']]
            fixture=min(r['tilt_deg'] for r in hold)>=P['criteria']['minimum_hold_tilt_deg']
            low_max=max(r['signal'] for r in hold);positive_min=min(r['signal'] for r in last);recovered=max(r['signal'] for r in rows if r['phase']=='observe')<=P['criteria']['unloaded_signal_max']
            force_pass=low_max<=P['criteria']['low_signal_max'] if fv<P['criteria']['low_force_bound_n'] else positive_min>=P['criteria']['positive_signal_min']
            result={'side':side,'vertical_force_n':fv,'status':'completed','fixture_valid':bool(fixture),'minimum_hold_tilt_deg':min(r['tilt_deg'] for r in hold),
                'maximum_hold_tilt_deg':max(r['tilt_deg'] for r in hold),'maximum_hold_signal':low_max,'minimum_positive_last_hold_signal':positive_min,
                'final_signal':rows[-1]['signal'],'unload_endpoint_signal':next(r['signal'] for r in reversed(rows) if r['time_s']<=observe_start),'maximum_observe_signal':max(r['signal'] for r in rows if r['phase']=='observe'),
                'minimum_hold_raw_fraction':min(r['raw_fraction'] for r in hold),'maximum_hold_raw_fraction':max(r['raw_fraction'] for r in hold),
                'unloaded_passed':bool(recovered),'force_criterion_passed':bool(force_pass),'physics_passed':bool(force_pass and recovered) if fixture else None,
                'point_local_m':point.tolist(),'trace':str(path/'trace.jsonl.gz')}
            index=next(i for i,r in enumerate(results) if r['side']==side and r['vertical_force_n']==fv)
            results[index]=result;completed+=1
            save(output/'results.json',{'label':label,'planned':10,'completed':completed,'results':results})
            print(json.dumps(result),flush=True)
            # A historical controller may fail the no-misclick criterion. An
            # invalid fixture, or a failure on the new model, stops this run.
            if not fixture or (label=='new' and not result['physics_passed']):
                save(output/'completion.json',{'completed':completed,'planned':10,'stopped':True,
                    'stop_reason':'fixture_invalid' if not fixture else 'new_model_physics_gate_failed',
                    'fixture_valid':bool(fixture),'physics_passed':result['physics_passed']})
                return results
    save(output/'completion.json',{'completed':10,'planned':10,'stopped':False,'fixture_valid':all(r['fixture_valid'] for r in results),'physics_passed':all(r['physics_passed'] is True for r in results)})
    return results

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--resources',required=True);p.add_argument('--output',required=True);p.add_argument('--label',choices=['new','old73c8676'],required=True);a=p.parse_args()
    results=run(a.resources,a.output,a.label)
    return int(any(r['status']!='completed' or r['fixture_valid'] is not True or
                   (a.label=='new' and r['physics_passed'] is not True) for r in results))

if __name__=='__main__':raise SystemExit(main())
