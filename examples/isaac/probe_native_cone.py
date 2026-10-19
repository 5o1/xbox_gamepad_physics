"""Measure a regular PhysX cone closing the existing articulation chain."""
import argparse
import json
import math
from pathlib import Path

from isaaclab.app import AppLauncher

p = argparse.ArgumentParser()
p.add_argument('--resources', type=Path, required=True)
p.add_argument('--source', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--cone-deg', type=float, default=23.)
p.add_argument('--skip-cone', action='store_true')
p.add_argument('--effort', type=float, default=.1)
p.add_argument('--target-deg', type=float, default=0.)
AppLauncher.add_app_launcher_args(p)
a = p.parse_args()
launcher = AppLauncher(a)
app = launcher.app

import torch
from pxr import Gf, Usd, UsdPhysics
from isaaclab.assets import Articulation
from isaaclab.sim import SimulationCfg, SimulationContext
from xbox_gamepad_physics.isaac import make_articulation_cfg
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.backends.common.physical import load_physical
from xbox_gamepad_physics.backends.common.model import Pose

c = a.resources/'common/xbox_one_s'
motion = motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()))
physical = load_physical(resource_directory=c/'physical')
a.output.mkdir(parents=True, exist_ok=True)
sim = SimulationContext(SimulationCfg(dt=.004, device=a.device, gravity=(0., 0., 0.),
                                      log_dir=str(a.output/'logs')))
arts = {}
for row, mode in enumerate(('fixed', 'free')):
    path = a.output/(mode+'.usda')
    stage = Usd.Stage.Open(str(a.source/(mode+'.usda')))
    for side in (() if a.skip_cone else ('left', 'right')):
        x = motion.joint_by_name[side+'_stick_x']
        joint = UsdPhysics.SphericalJoint.Define(stage, '/Gamepad/Joints/'+side+'_cone')
        joint.CreateBody0Rel().SetTargets(['/Gamepad/Links/controller_body'])
        joint.CreateBody1Rel().SetTargets(['/Gamepad/Links/'+side+'_stick_y_frame'])
        joint.CreateLocalPos0Attr(Gf.Vec3f(*x.origin))
        joint.CreateLocalPos1Attr(Gf.Vec3f(0))
        joint.CreateAxisAttr('Z')
        joint.CreateConeAngle0LimitAttr(a.cone_deg)
        joint.CreateConeAngle1LimitAttr(a.cone_deg)
        joint.CreateExcludeFromArticulationAttr(True)
    stage.GetRootLayer().Export(str(path))
    arts[mode] = Articulation(make_articulation_cfg(path, motion=motion, physical=physical,
        prim_path='/World/'+mode, root_pose=Pose((row*.3, 0., .1))))
sim.reset()
records = {mode: [] for mode in arts}
for art in arts.values():
    art.update(.004)
    targets = torch.zeros_like(art.data.joint_pos)
    for name in ('left_stick_x', 'left_stick_y'):
        targets[:, art.joint_names.index(name)] = math.radians(a.target_deg)
    art.set_joint_position_target(targets)
    effort = torch.zeros_like(art.data.joint_pos)
    for name in ('left_stick_x', 'left_stick_y'):
        effort[:, art.joint_names.index(name)] = a.effort
    art.set_joint_effort_target(effort)
for tick in range(150):
    for art in arts.values():
        art.write_data_to_sim()
    sim.step(render=False)
    for mode, art in arts.items():
        art.update(.004)
        ids = [art.joint_names.index('left_stick_'+axis) for axis in ('x', 'y')]
        q = art.data.joint_pos[0, ids].double()
        v = art.data.joint_vel[0, ids].double()
        angle = torch.acos(torch.clamp(torch.cos(q).prod(), -1., 1.))
        gradient = torch.stack((torch.sin(q[0])*torch.cos(q[1]),
                                torch.cos(q[0])*torch.sin(q[1])))/torch.sin(angle)
        records[mode].append([tick, *q.tolist(), *v.tolist(), angle.item(), (gradient*v).sum().item()])
result = {mode: {'joint_names': art.joint_names, 'num_joints': len(art.joint_names),
                'max_angle_deg': max(math.degrees(r[5]) for r in records[mode]),
                'last': records[mode][-1], 'rows': records[mode]}
          for mode, art in arts.items()}
(a.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({mode: {k: v for k, v in data.items() if k != 'rows'}
                  for mode, data in result.items()}), flush=True)
app.close(skip_cleanup=True)
