"""Gravity/no-gravity release diagnosis; default sleep threshold is untouched."""
import argparse
import json
import math
from pathlib import Path
from unittest.mock import patch
import numpy as np
import sapien
from tests.acceptance.robotwin import executor, run_suite
from tests.acceptance.robotwin.stick_click import setup, shaft
from xbox_gamepad_physics.robotwin import mappings


def tree(child, links):
    chosen = [child]
    while True:
        new = [l for l in links if l not in chosen and l.joint.get_parent_link() in chosen]
        if not new: return chosen
        chosen.extend(new)


def measure(e, subtree, qi):
    energy = 0.
    velocities = []
    for link in subtree:
        linear = np.asarray(link.linear_velocity)
        angular = np.asarray(link.angular_velocity)
        rotation = (link.pose*link.cmass_local_pose).to_transformation_matrix()[:3,:3]
        w = rotation.T @ angular
        kinetic = .5*link.mass*float(linear@linear)+.5*float((w*w)@np.asarray(link.inertia))
        energy += kinetic
        velocities.append(dict(name=link.name,linear_m_s=linear.tolist(),angular_rad_s=angular.tolist(),kinetic_j=kinetic))
    return dict(q_m=float(e.art.get_qpos()[qi]),qvel_m_s=float(e.art.get_qvel()[qi]),
        sleeping=bool(e.art.root.sleeping),kinetic_j=energy,
        kinetic_j_per_kg=energy/sum(l.mass for l in subtree),links=velocities)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    sapien.physx.set_scene_config(cpu_workers=0,enable_tgs=True)
    all_rows=[]
    def cpu_scene(**kwargs):
        previous=sapien.physx.get_scene_config()
        sapien.physx.set_scene_config(gravity=[0,0,-9.81] if gravity else [0,0,0])
        try:return run_suite.cpu_scene(**kwargs)
        finally:sapien.physx.set_scene_config(previous)
    with patch.object(mappings,'apply_preload'), patch.object(executor,'create_scene',side_effect=cpu_scene):
        for dt in (.004,.001):
            for gravity in (True,False):
                for wake in (False,True):
                    e=setup('left',20)
                    e.scene.set_timestep(dt);e.dt=dt
                    j=e.joints['left_stick_click'];child=j.get_child_link()
                    qi=list(e.joints).index(j.name)
                    subtree=tree(child,e.art.get_links())
                    positive=(child.pose*j.get_pose_in_child()).to_transformation_matrix()[:3,0]
                    mass=sum(l.mass for l in subtree)
                    metadata=dict(dt_s=dt,gravity=gravity,wake_each_step=wake,
                        mass_kg=mass,subtree=[dict(name=l.name,mass_kg=l.mass,inertia_kg_m2=l.inertia.tolist()) for l in subtree],
                        axis_world=positive.tolist(),gravity_projection_n=mass*float(positive@np.array([0,0,-9.81])) if gravity else 0.,
                        stiffness=j.stiffness,damping=j.damping,friction=j.friction,force_limit=j.force_limit,
                        predicted_equilibrium_m=mass*float(positive@np.array([0,0,-9.81]))/j.stiffness if gravity else 0.,
                        sleep_threshold=e.art.get_sleep_threshold())
                    for _ in range(round(.5/dt)):
                        axis,center=shaft(e);e.cap.add_force_at_point(8*axis,center);e.scene.step()
                    before=measure(e,subtree,qi);rows=[];previous=None;first_sleep=None
                    for i in range(round(2/dt)):
                        if wake:e.art.root.wake_up()
                        e.scene.step()
                        row=dict(time_s=(i+1)*dt,**measure(e,subtree,qi))
                        if row['sleeping'] and first_sleep is None:first_sleep=dict(time_s=row['time_s'],before=previous,after=row)
                        rows.append(row);previous=row
                    record=dict(**metadata,before_release=before,first_sleep=first_sleep,final=rows[-1],
                        final_force_residual_n=metadata['gravity_projection_n']-j.stiffness*rows[-1]['q_m'])
                    all_rows.append(record)
                    name=f'dt-{dt}-g-{int(gravity)}-wake-{int(wake)}'
                    (a.output/(name+'.json')).write_text(json.dumps(dict(metadata=metadata,rows=rows),indent=2)+'\n')
                    print(json.dumps(record),flush=True)
                    (a.output/'summary.json').write_text(json.dumps(all_rows,indent=2)+'\n')

if __name__=='__main__':main()
