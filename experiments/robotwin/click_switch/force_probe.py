"""Small actual-engine check of zero-width limits and incoming force sign."""
import json
import math
from unittest.mock import patch
import numpy as np
import sapien
from xbox_gamepad_physics.robotwin import mappings
from tests.acceptance.robotwin.stick_click import setup, shaft
from tests.acceptance.robotwin import executor, run_suite

sapien.physx.set_scene_config(cpu_workers=0, enable_tgs=True)
with patch.object(mappings, 'apply_preload'), patch.object(executor, 'create_scene', side_effect=run_suite.cpu_scene):
    e = setup('left')
j = e.joints['left_stick_click']
child = j.get_child_link()
i = e.art.get_links().index(child)
qi = list(e.joints).index(j.name)
j.set_limits([[0.,0.]])
print(json.dumps(dict(type='api', link=child.name,index=i,dof=len(e.art.get_qpos()),limits=j.get_limits().tolist(),threshold=e.art.get_sleep_threshold(),methods=[n for n in dir(e.art) if 'force' in n or 'flag' in n])),flush=True)
for angle in (0,12,20):
    e.joints['left_stick_x'].set_drive_target(math.radians(angle))
    for _ in range(300): e.scene.step()
    for force in (0,3,7,8,12,0):
        for _ in range(100):
            axis,center=shaft(e)
            e.cap.add_force_at_point(force*axis,center)
            e.scene.step()
        print(json.dumps(dict(type='force',angle=angle,force=force,q=e.art.get_qpos()[qi].item(),wrench=e.art.get_link_incoming_joint_forces()[i].tolist(),qf=e.art.get_qf().tolist(),sleeping=bool(e.art.root.sleeping))),flush=True)
j.set_limits([[0.,.0004]])
for force in (8,0):
    for _ in range(500):
        axis,center=shaft(e)
        if force: e.cap.add_force_at_point(force*axis,center)
        e.scene.step()
    print(json.dumps(dict(type='unlock',force=force,q=e.art.get_qpos()[qi].item(),wrench=e.art.get_link_incoming_joint_forces()[i].tolist(),sleeping=bool(e.art.root.sleeping))),flush=True)
