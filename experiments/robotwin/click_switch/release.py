"""1 kHz release trajectories for both states, tilt fixtures removed on release."""
import argparse
import json
import math
from pathlib import Path
import time
from unittest.mock import patch
import numpy as np
import sapien

from experiments.robotwin.click_switch.override import policy
from experiments.robotwin.click_switch.diagnose_gravity import tree, measure
from experiments.robotwin.station_rtf.overrides import policy as station_policy
from tests.acceptance.robotwin import executor, run_suite
from tests.acceptance.robotwin.stick_click import setup, shaft, sample


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['pure','hybrid'],required=True)
    p.add_argument('--iterations',nargs=2,type=int,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--duration-s',type=float,default=5.)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();results=[]
    sapien.physx.set_scene_config(cpu_workers=0,enable_tgs=True)
    with policy(mode=a.mode) as switches, station_policy(iterations=a.iterations), \
         patch.object(executor,'create_scene',side_effect=run_suite.cpu_scene):
        for side in ('left','right'):
            for angle in (0,2,23):
                for press in ('full','just_over'):
                    e=setup(side,hold=False);e.dt=.001;e.scene.set_timestep(e.dt)
                    switch=e.gamepad.click_switch
                    joints=[e.joints[side+'_stick_'+axis] for axis in ('x','y')]
                    passive=[(j.stiffness,j.damping,j.force_limit,j.drive_mode,float(j.get_drive_target()[0])) for j in joints]
                    for j,target in zip(joints,(math.radians(angle),0.)):
                        j.set_drive_properties(100,1,force_limit=10,mode='force');j.set_drive_target(target)
                    for _ in range(300):e.scene.step()
                    for i in range(250):
                        axis,center=shaft(e)
                        cosine=sample(e)['cosine']
                        force=12/cosine if press=='full' else 1.01*switch.unlock_n/cosine
                        e.cap.add_force_at_point(force*axis,center);e.scene.step()
                        state=sample(e)
                        if press=='just_over' and not switch.locked[0 if side=='left' else 1] and state['q_m']>0:break
                    prep_steps=i+1
                    initial=sample(e)
                    # Remove fixture drives and force simultaneously. No reset,
                    # q writes, forced sleep, or force(0) call during the release.
                    for j,(k,d,f,mode,target) in zip(joints,passive):
                        j.set_drive_properties(k,d,force_limit=f,mode=mode);j.set_drive_target(target)
                    binding=e.gamepad._bindings[side+'_stick_click']
                    subtree=tree(binding.joint.get_child_link(),e.art.get_links())
                    rows=[];first_sleep=None;previous=None;first_q_return=None
                    for i in range(round(a.duration_s/e.dt)):
                        before_energy = {'time_s':i*e.dt, **sample(e), **measure(e,subtree,binding.qpos_offset)} if first_sleep is None else None
                        e.scene.step();state=sample(e);q=e.gamepad.joint_positions()
                        sleeping=bool(e.art.root.sleeping)
                        within=abs(state['q_m'])<=3e-6 and state['shaft_angle_deg']<=.1
                        row=[(i+1)*e.dt,state['q_m'],e.art.get_qvel()[binding.qpos_offset],
                            q[side+'_stick_x'],q[side+'_stick_y'],state['shaft_angle_deg'],
                            state['signal'],float(sleeping),switch.last_load_n[0 if side=='left' else 1],
                            float(switch.locked[0 if side=='left' else 1]),
                            e.art.get_qf()[binding.qpos_offset],float(within)]
                        if abs(state['q_m'])<=3e-6 and first_q_return is None:first_q_return=row[0]
                        if sleeping and first_sleep is None:
                            first_sleep=dict(time_s=row[0],before=before_energy,
                                after={**state,**measure(e,subtree,binding.qpos_offset)})
                        if i<600 or sleeping and first_sleep['time_s']==row[0]:
                            previous={'time_s':row[0],**state,**measure(e,subtree,binding.qpos_offset)}
                        rows.append(row)
                    values=np.asarray(rows)
                    invalid=np.flatnonzero(values[:,-1]==0)
                    stable_return_s=float(values[invalid[-1]+1,0]) if len(invalid) and invalid[-1]+1<len(values) else (None if len(invalid) else .001)
                    name=f'{side}-{angle}-{press}'
                    np.savez_compressed(a.output/(name+'.npz'),trajectory=values,
                        columns=np.array(['time_s','click_q_m','click_qvel_m_s','tilt_x_rad','tilt_y_rad',
                            'shaft_angle_deg','signal','sleeping','last_load_n','locked','click_qf_n','within']))
                    result=dict(side=side,angle_deg=angle,press=press,prep_steps=prep_steps,
                        applied_force_n=force,release_start=initial,first_q_return_s=first_q_return,
                        stable_return_s=stable_return_s,first_sleep=first_sleep,final=sample(e),
                        sleeping_at_end=bool(e.art.root.sleeping),switch=switch.snapshot(),
                        final_energy=measure(e,subtree,binding.qpos_offset),
                        final_within=bool(values[-1,-1]),press_reached_full=initial['raw_fraction']>=.95)
                    results.append(result)
                    receipt=dict(mode=a.mode,iterations=a.iterations,dt_s=.001,duration_s=a.duration_s,
                        click_tolerance_m=3e-6,tilt_tolerance_deg=.1,
                        elapsed_s=time.monotonic()-started,results=results)
                    (a.output/'summary.json').write_text(json.dumps(receipt,indent=2)+'\n')
                    print(json.dumps({k:result[k] for k in ['side','angle_deg','press','stable_return_s','sleeping_at_end','final_within']}),flush=True)

if __name__=='__main__':main()
