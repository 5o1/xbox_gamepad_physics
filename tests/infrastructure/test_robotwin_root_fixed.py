"""Public root transitions preserve the teleop record contract without SAPIEN."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys
import unittest

from infrastructure.test_robotwin_runtime import FakeArticulation
from xbox_gamepad_physics.robotwin.articulation import XboxOneSArticulation
from xbox_gamepad_physics.robotwin.errors import SceneCompatibilityError
from xbox_gamepad_physics.controller import AxisSignalMapping, GamepadSignalController
from xbox_gamepad_physics.state import XBOX_ONE_S_CHANNELS


class FakeGpuSystem:
    pass


class RootFixedTest(unittest.TestCase):
    def setUp(self):
        self.backend=patch.dict(sys.modules, {'sapien.physx':SimpleNamespace(PhysxGpuSystem=FakeGpuSystem)})
        self.backend.start();self.addCleanup(self.backend.stop)
        self.art=FakeArticulation();self.art.qpos=[.001,.25];self.art.qvel=[.2,.3]
        self.art.root=SimpleNamespace(joint=SimpleNamespace(type='free'),wake_up=Mock())
        self.art.get_root_pose=Mock(return_value=SimpleNamespace(p=[1,2,3],q=[1,0,0,0]))
        self.art.set_root_linear_velocity=Mock();self.art.set_root_angular_velocity=Mock()
        for j in self.art.joints:j.get_drive_target=Mock(return_value=[.125])
        self.scene=SimpleNamespace(physx_system=object())
        controller=GamepadSignalController.xbox_one_s([AxisSignalMapping('left_x','left_stick_x',-1,1)])
        self.pad=XboxOneSArticulation(self.art,['button_a','left_stick_x'],controller,scene=self.scene)

    def test_transition_fields_state_and_release_velocity(self):
        self.assertFalse(self.pad.root_fixed)
        event=self.pad.set_root_fixed(True)
        self.assertTrue(self.pad.root_fixed)
        self.assertEqual(event,{'from':'moving','to':'fixed','pose':[1.,2.,3.,1.,0.,0.,0.],
            'joint_positions':{'button_a':.001,'left_stick_x':.25},
            'drive_targets':{'button_a':.125,'left_stick_x':.125},
            'signal_delta':dict.fromkeys(XBOX_ONE_S_CHANNELS,0.)})
        # Fixed solver semantics are retained; no new explicit velocity writes.
        self.art.set_root_linear_velocity.assert_not_called()
        self.art.set_root_angular_velocity.assert_not_called()
        event=self.pad.set_root_fixed(False)
        self.assertEqual((event['from'],event['to']),('fixed','moving'))
        self.art.set_root_linear_velocity.assert_called_once_with([0,0,0])
        self.art.set_root_angular_velocity.assert_called_once_with([0,0,0])
        self.assertEqual(self.art.root.wake_up.call_count,2)
        self.assertEqual(self.art.qpos,[.001,.25]);self.assertEqual(self.art.qvel,[.2,.3])
        self.assertEqual(self.art.root_poses,[])
        for joint in self.art.joints:self.assertEqual(joint.target_calls,[])

    def test_repeated_call_does_not_snapshot_write_or_wake(self):
        for fixed in (False,True):
            self.art.root.joint.type='fixed' if fixed else 'free'
            self.assertIsNone(self.pad.set_root_fixed(fixed))
        self.art.get_root_pose.assert_not_called();self.art.root.wake_up.assert_not_called()
        self.art.set_root_linear_velocity.assert_not_called();self.art.set_root_angular_velocity.assert_not_called()
        for j in self.art.joints:j.get_drive_target.assert_not_called()

    def test_non_bool_is_rejected_before_backend_access(self):
        for value in (0,1,None,'fixed',[],object()):
            with self.subTest(value=value),self.assertRaisesRegex(TypeError,'fixed must be bool'):
                self.pad.set_root_fixed(value)
        self.assertFalse(self.pad.root_fixed);self.art.root.wake_up.assert_not_called()

    def test_root_fixed_is_read_only_and_reflects_loaded_state(self):
        for kind,expected in (('fixed',True),('free',False),('undefined',False)):
            self.art.root.joint.type=kind;self.assertIs(self.pad.root_fixed,expected)
        with self.assertRaises(AttributeError):self.pad.root_fixed=True

    def test_gpu_and_batch_backend_is_rejected_without_mutation(self):
        self.scene.physx_system=FakeGpuSystem()
        with self.assertRaisesRegex(SceneCompatibilityError,'CPU PhysX'):
            self.pad.set_root_fixed(True)
        self.assertFalse(self.pad.root_fixed);self.art.get_root_pose.assert_not_called()
        self.art.root.wake_up.assert_not_called()

    def test_ignored_backend_change_is_an_error(self):
        class IgnoredJoint:
            @property
            def type(self):return 'free'
            @type.setter
            def type(self,value):pass
        self.art.root.joint=IgnoredJoint()
        with self.assertRaisesRegex(SceneCompatibilityError,'did not apply'):
            self.pad.set_root_fixed(True)
        self.art.root.wake_up.assert_not_called()
