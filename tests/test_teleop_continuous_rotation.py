"""Continuous target/drive turns without SAPIEN or GPU dependencies."""
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np
import yaml
from teleop.gripper import GripperRig
from teleop.inputs import Inputs
from teleop.session import Command, command_target, quat_multiply, rotation_quaternion
from teleop.views import VIEWS

CFG=yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/teleop_gripper.yaml').read_text())


class ContinuousRotationTest(unittest.TestCase):
    def test_world_axes_target_and_drive_follow_through_two_turns_and_q_signs(self):
        for axis in ((1,0,0),(0,1,0),(0,0,1)):
            pose=[0,0,1,1,0,0,0]
            rig=GripperRig.__new__(GripperRig)
            rig.cfg=CFG['teleop'];rig.finger_target=.02
            art=Mock();art.get_root_linear_velocity.return_value=np.zeros(3)
            art.get_root_angular_velocity.return_value=np.zeros(3)
            art.get_active_joints.return_value=[]
            for tick in range(1,161):
                pose,_=command_target(pose,.02,Command(rotation=axis),CFG['teleop']['input'])
                expected=rotation_quaternion([x*math.radians(tick*5) for x in axis])
                for x,y in zip(pose[3:],expected):self.assertAlmostEqual(x,y,places=12)
                # Actual is one degree behind, including across 180/360/720 deg.
                actual=quat_multiply(rotation_quaternion([-x*math.radians(1) for x in axis]),pose[3:])
                rig.target=pose
                for sign in (1,-1):
                    art.get_root_pose.return_value=SimpleNamespace(p=np.array(pose[:3]),q=np.array(actual)*sign)
                    drive=rig.drive(art,0)
                    for x,y in zip(drive['rotation_error_rad'],axis):self.assertAlmostEqual(x,y*math.radians(1),places=12)
                    self.assertGreater(sum(x*y for x,y in zip(drive['torque_nm'],axis)),0)

    def test_held_keys_keep_direction_for_800_degrees_in_every_view(self):
        for view in VIEWS:
            for key in ('KeyW','KeyS','KeyA','KeyD'):
                controls=Inputs(camera_relative=True,input_config=CFG['teleop']['input'],cursor_config=CFG['stream']['cursor'])
                for seq,m in enumerate(({'kind':'focus'},{'kind':'view','view':view},{'kind':'keys','keys':[key]}),1):
                    controls.accept({'seq':seq,**m},0)
                pose=list(CFG['stream']['cursor']['initial_pose']);first=None;total=0
                for step in range(2080):
                    cmd=controls.command(step*.004,pose=pose,finger_target=.02)
                    controls.commit()
                    if any(cmd.rotation):
                        first=first or cmd.rotation
                        self.assertGreater(sum(x*y for x,y in zip(first,cmd.rotation)),.999999)
                        total+=5
                    pose,_=command_target(pose,.02,cmd,CFG['teleop']['input'])
                self.assertEqual(total,800)
