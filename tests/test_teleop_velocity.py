"""Schema-4 SI velocities, traction geometry and release without rebasing."""
import math
from pathlib import Path
import unittest
import yaml
from teleop.session import Command,command_target,limit_target,rotation_quaternion,quat_multiply
from teleop.inputs import Inputs

CFG=yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/teleop_gripper.yaml').read_text())
INPUT=CFG['teleop']['input'];CURSOR=CFG['stream']['cursor']


class VelocityTest(unittest.TestCase):
    def test_position_and_quaternion_tethers_use_distance_and_shortest_arc(self):
        actual=[1,2,3,1,0,0,0];desired=[2,4,6,*rotation_quaternion([0,0,math.pi/2])]
        target=limit_target(desired,actual,.01,5)
        self.assertAlmostEqual(math.dist(target[:3],actual[:3]),.01,places=12)
        self.assertAlmostEqual(2*math.acos(abs(target[3])),math.radians(5),places=12)
        negative=[*actual[:3],-1,0,0,0]
        self.assertEqual(limit_target(desired,negative,.01,5)[:3],target[:3])
        # A 359-degree target is only -1 degree away; do not clamp cumulative angle.
        pose=[*actual[:3],*rotation_quaternion([0,0,math.radians(359)])]
        self.assertAlmostEqual(abs(sum(a*b for a,b in zip(limit_target(pose,actual,.01,5)[3:],pose[3:]))),1)

    def controls(self,keys):
        c=Inputs(camera_relative=True,input_config=INPUT,cursor_config=CURSOR,schema_version=4)
        c.accept({'seq':1,'kind':'focus'},0);c.accept({'seq':2,'kind':'keys','keys':keys},0)
        return c

    def test_every_physics_step_integrates_both_speed_profiles(self):
        for fine,expected in ((False,.1),(True,.02)):
            c=self.controls(['KeyQ']+(['ShiftLeft'] if fine else []));p=[0,0,1,1,0,0,0]
            for step in range(500):
                cmd=c.command(step*.004,pose=p,finger_target=.02);c.commit()
                self.assertAlmostEqual(cmd.linear_velocity_m_s[2],expected)
                p,_=command_target(p,.02,cmd,INPUT,dt=.004)
            self.assertAlmostEqual(p[2],1+2*expected,places=12)

    def test_release_preserves_existing_pd_offset_and_mouse_does_not_starve_velocity(self):
        c=self.controls(['KeyQ']);pose=[0,0,1.002,1,0,0,0];actual=[0,0,1,1,0,0,0]
        c.command(0,pose=pose,finger_target=.02);c.commit()
        c.accept({'seq':3,'kind':'keys','keys':[]},1)
        cmd=c.command(.004,pose=pose,finger_target=.02)
        target,_=command_target(pose,.02,cmd,INPUT,dt=.004,actual_pose=actual)
        self.assertEqual(target,pose)
        c.accept({'seq':4,'kind':'keys','keys':['KeyW','ShiftLeft']},2)
        c.accept({'seq':5,'kind':'delta','screen_pixels':[10,0]},2)
        cmd=c.command(.008,pose=pose,finger_target=.02)
        self.assertAlmostEqual(math.sqrt(sum(v*v for v in cmd.angular_velocity_rad_s)),math.radians(20))
        self.assertAlmostEqual(cmd.translation[0]*INPUT['coarse']['translation_m'],.001)

    def test_mouse_and_keyboard_share_tether_and_legacy_repeat_remains_available(self):
        pose=[0,0,1,1,0,0,0];c=self.controls([])
        c.accept({'seq':3,'kind':'delta','screen_pixels':[10000,0]},0)
        target,_=command_target(pose,.02,c.command(0,pose=pose,finger_target=.02),INPUT,dt=.004,actual_pose=pose)
        self.assertAlmostEqual(math.dist(target[:3],pose[:3]),INPUT['traction']['translation_limit_m'])
        old=Inputs(camera_relative=True,input_config=INPUT,cursor_config=CURSOR,schema_version=3)
        old.accept({'seq':1,'kind':'focus'},0);old.accept({'seq':2,'kind':'keys','keys':['KeyQ']},0)
        self.assertNotEqual(old.command(0,pose=pose,finger_target=.02).translation,(0,0,0))
        self.assertEqual(old.command(.004,pose=pose,finger_target=.02).translation,(0,0,0))

    def test_inward_velocity_releases_saturated_preload_but_release_does_not(self):
        actual=[0,0,1,1,0,0,0];p=[0,0,.99,1,0,0,0]
        held,_=command_target(p,.02,Command(),INPUT,dt=.004,actual_pose=actual)
        self.assertEqual(held,p)
        reversed_pose,_=command_target(p,.02,Command(linear_velocity_m_s=(0,0,.1)),INPUT,dt=.004,actual_pose=actual)
        self.assertGreater(reversed_pose[2],actual[2])
