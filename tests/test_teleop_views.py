"""Cursor projection, rotation signs and absolute grip commands for every camera."""
import math
from pathlib import Path
import unittest
import yaml
from teleop.inputs import Inputs
from teleop.cursor import front_point
from teleop.session import command_target
from teleop.views import VIEWS, camera_basis, project

ROOT=Path(__file__).resolve().parents[1]
CFG=yaml.safe_load((ROOT/'configs/teleop_gripper.yaml').read_text())
INPUT=CFG['teleop']['input'];CURSOR=CFG['stream']['cursor'];POSE=CURSOR['initial_pose']


class CameraInputTest(unittest.TestCase):
    def state(self,view):
        state=Inputs(camera_relative=True,input_config=INPUT,cursor_config=CURSOR)
        for seq,message in enumerate(({'kind':'focus'},{'kind':'view','view':view}),1):
            state.accept({'seq':seq,**message},0)
        return state

    def command(self,state):
        return state.command(0,pose=POSE,finger_target=.02)

    def test_mouse_right_and_down_projection_for_every_view_and_gain(self):
        for view,(_,target,_,_) in VIEWS.items():
            for fine,gain in ((False,.1),(True,.025)):
                for pixels,axis in (([10,0],0),([0,10],1)):
                    with self.subTest(view=view,fine=fine,pixels=pixels):
                        state=self.state(view);state.accept({'seq':3,'kind':'delta','screen_pixels':pixels,'fine':fine},0)
                        command=self.command(state)
                        root=[*target,*POSE[3:]];new,_=command_target(root,.02,command,INPUT)
                        before,after=project(view,root[:3]),project(view,new[:3])
                        self.assertGreater(after[axis]-before[axis],0)
                        self.assertAlmostEqual(after[1-axis],before[1-axis],places=12)
                        distance=math.dist(new[:3],root[:3])
                        self.assertAlmostEqual(distance,10*gain/1000,places=12)

    def test_q_reduces_distance_to_camera(self):
        for view,(camera,_,_,_) in VIEWS.items():
            state=self.state(view);state.accept({'seq':3,'kind':'keys','keys':['KeyQ']},0)
            root,_=command_target(POSE,.02,self.command(state),INPUT)
            self.assertLess(math.dist(root[:3],camera),math.dist(POSE[:3],camera))

    def test_w_and_a_move_front_up_and_left_about_unchanged_root(self):
        for view in VIEWS:
            for key,axis in (('KeyW',1),('KeyA',0)):
                with self.subTest(view=view,key=key):
                    state=self.state(view);state.accept({'seq':3,'kind':'keys','keys':[key]},0)
                    cmd=self.command(state);root,_=command_target(POSE,.02,cmd,INPUT)
                    before=project(view,front_point(POSE,CURSOR['front_reference_m']))
                    after=project(view,front_point(root,CURSOR['front_reference_m']))
                    self.assertLess(after[axis],before[axis])
                    self.assertEqual(root[:3],POSE[:3])
                    # Axis remains screen right for pitch / up for yaw, no roll control.
                    desired=camera_basis(view)[0 if key=='KeyW' else 1]
                    self.assertAlmostEqual(abs(sum(x*y for x,y in zip(cmd.rotation,desired))),1)

    def test_left_and_right_click_reach_preload_and_open_targets(self):
        for view in VIEWS:
            for grip,target in (('close',-.002),('open',.04765)):
                for fine in (False,True):
                    state=self.state(view);state.accept({'seq':3,'kind':'delta','grip':grip,'fine':fine},0)
                    _,actual=command_target(POSE,.02,self.command(state),INPUT)
                    self.assertAlmostEqual(actual,target,places=15)
                    # A subsequent empty step keeps the same target.
                    _,held=command_target(POSE,actual,state.command(.004,pose=POSE,finger_target=actual),INPUT)
                    self.assertEqual(held,actual)

    def test_mouse_queued_view_uses_executing_boundary_and_post_step_ack(self):
        state=self.state('left')
        state.accept({'seq':3,'kind':'delta','screen_pixels':[10,0]},0)
        state.accept({'seq':4,'kind':'view','view':'right'},0)
        state.accept({'seq':5,'kind':'delta','screen_pixels':[10,0]},0)
        first=self.command(state);self.assertEqual(state.applied_seq,0);self.assertEqual(state.commit(),3)
        second=state.command(.004,pose=POSE,finger_target=.02);self.assertEqual(state.commit(),5)
        for command,view in ((first,'left'),(second,'right')):
            root,_=command_target(POSE,.02,command,INPUT)
            self.assertEqual(tuple(round((x-y)/.001,10) for x,y in zip(root[:3],POSE[:3])),
                             tuple(round(x,10) for x in camera_basis(view)[0]))

    def test_unarmed_mouse_and_pending_motion_are_discarded_by_stop(self):
        state=Inputs(camera_relative=True,input_config=INPUT,cursor_config=CURSOR)
        state.accept({'seq':1,'kind':'delta','screen_pixels':[100,100]},0)
        self.assertEqual(self.command(state).translation,(0,0,0))
        self.assertEqual(state.prepared_seq,0);self.assertEqual(state.cancelled,[1])
        state.accept({'seq':2,'kind':'focus'},1)
        state.accept({'seq':3,'kind':'delta','screen_pixels':[100,100]},1)
        state.accept({'seq':4,'kind':'stop','reason':'pointer-unlocked'},1)
        self.assertEqual(self.command(state).translation,(0,0,0));self.assertTrue(state.hold)
        state.accept({'seq':5,'kind':'focus'},2)
        self.assertEqual(self.command(state).translation,(0,0,0))

    def test_timeout_cancels_pending_mouse_without_falsely_acknowledging_it(self):
        state=self.state('front')
        state.accept({'seq':3,'kind':'delta','screen_pixels':[10,0],'received_ns':1000000000},0)
        self.command(state);self.assertEqual(state.commit(),3)
        state.accept({'seq':4,'kind':'delta','screen_pixels':[10,0],'received_ns':1000000000},1)
        cmd=state.command(.2,1200000000,pose=POSE,finger_target=.02)
        self.assertEqual(cmd.translation,(0,0,0));self.assertTrue(state.hold)
        self.assertEqual(state.commit(),3);self.assertEqual(state.cancelled,[4])
        state.accept({'seq':5,'kind':'delta','screen_pixels':[10,0]},2)
        self.command(state);self.assertEqual(state.commit(),3)
        self.assertEqual(state.cancelled,[4,5])

    def test_mouse_does_not_starve_held_rotation_repeat_or_change_step_size(self):
        state=self.state('front');state.accept({'seq':3,'kind':'keys','keys':['KeyW','ShiftLeft']},0)
        state.accept({'seq':4,'kind':'delta','screen_pixels':[10,0],'fine':False},0)
        cmd=self.command(state)
        self.assertAlmostEqual(math.sqrt(sum(x*x for x in cmd.rotation)),.2) # fine 1 deg in coarse 5-deg ticks
        self.assertEqual(state.command(.004,pose=POSE,finger_target=.02).rotation,(0,0,0))
        state.accept({'seq':5,'kind':'delta','screen_pixels':[10,0],'fine':False},13)
        again=state.command(.052,pose=POSE,finger_target=.02)
        self.assertAlmostEqual(math.sqrt(sum(x*x for x in again.rotation)),.2)


if __name__=='__main__':unittest.main()
