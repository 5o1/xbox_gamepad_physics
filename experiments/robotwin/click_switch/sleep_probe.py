"""Distinguish limit-width and wrench-read effects on natural idle sleep."""
import argparse
import json
from pathlib import Path
import time
from unittest.mock import patch
import numpy as np
import sapien
from tests.acceptance.robotwin import executor, run_suite
from tests.acceptance.robotwin.stick_click import setup
from xbox_gamepad_physics.robotwin import mappings
from experiments.robotwin.station_rtf.overrides import policy as station_policy


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);results=[];started=time.monotonic()
    sapien.physx.set_scene_config(cpu_workers=0,enable_tgs=True)
    with patch.object(mappings,'apply_preload'), patch.object(executor,'create_scene',side_effect=run_suite.cpu_scene):
        for iterations in ((64,16),(10,1)):
            for width in (None,0.,1e-6):
                for read_forces in (False,True):
                    with station_policy(iterations=iterations):e=setup('left',hold=False)
                    e.dt=.001;e.scene.set_timestep(e.dt)
                    if width is not None:
                        for side in ('left','right'):e.joints[side+'_stick_click'].set_limits([[0.,width]])
                    # setup may already have slept with the original wide limits.
                    # One wake makes the new limits participate before timing sleep.
                    e.art.root.wake_up()
                    first_sleep=None;rows=[]
                    for i in range(5000):
                        if read_forces:e.art.get_link_incoming_joint_forces()
                        e.scene.step()
                        sleeping=bool(e.art.root.sleeping)
                        if sleeping and first_sleep is None:first_sleep=(i+1)*e.dt
                        if i%100==0:rows.append(dict(time_s=(i+1)*e.dt,sleeping=sleeping,qpos=e.art.get_qpos().tolist(),qvel=e.art.get_qvel().tolist()))
                    r=dict(iterations=iterations,width_m=width,read_forces=read_forces,first_sleep_s=first_sleep,
                        sleeping_at_end=sleeping,qpos=e.gamepad.joint_positions(),qvel=e.art.get_qvel().tolist(),
                        qf=e.art.get_qf().tolist(),sleep_threshold=e.art.get_sleep_threshold(),rows=rows)
                    results.append(r)
                    (a.output/'summary.json').write_text(json.dumps(dict(elapsed_s=time.monotonic()-started,results=results),indent=2)+'\n')
                    print(json.dumps({k:r[k] for k in ('iterations','width_m','read_forces','first_sleep_s','sleeping_at_end')}),flush=True)

if __name__=='__main__':main()
