"""Freeze restores independent limits and preserves preload across repeated cycles."""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from teleop.gripper import GripperRig, ratchet_upper
from teleop.gamepad import GamepadSwitch


class RatchetTest(unittest.TestCase):
    def test_independent_caps_restore_and_next_freeze(self):
        joints=[]
        for name in ('fl_joint7','fl_joint8'):
            j=Mock(name=name);j.name=name;j.get_drive_target.return_value=[-.002];joints.append(j)
        pose=SimpleNamespace(p=[0,0,.2],q=[1,0,0,0])
        main=Mock();main.root.joint.type='free'
        main.get_root_pose.return_value=pose;main.get_active_joints.return_value=joints
        main.get_qpos.return_value=[.0343,.03599]
        rig=GripperRig.__new__(GripperRig)
        rig.main=main;rig.secondary=Mock();rig.scene=Mock()
        rig.entities={'secondary':[Mock()]};rig.inactive_data={}
        rig.cfg={'freeze':{'limit_margin_m':1e-5}}
        rig.original_limits={j.name:[[0,.04765]] for j in joints}
        rig.initialize=Mock();rig.set_groups=Mock()
        with patch('teleop.gripper.articulation_data',return_value={}):
            rig.freeze(1)
            self.assertEqual(main.root.joint.type,'fixed')
            self.assertAlmostEqual(joints[0].set_limits.call_args.args[0][0][1],.03431)
            self.assertAlmostEqual(joints[1].set_limits.call_args.args[0][0][1],.036)
            self.assertEqual(rig.frozen['finger_targets'],{'fl_joint7':-.002,'fl_joint8':-.002})
            main.set_qpos.assert_not_called();rig.scene.remove_articulation.assert_not_called()
            rig.restore(3)
            self.assertEqual(main.root.joint.type,'free')
            self.assertEqual(rig.target,[0,0,.2,1,0,0,0]);self.assertEqual(rig.finger_target,-.002)
            for j in joints:
                self.assertEqual(j.set_limits.call_args.args[0],[[0,.04765]])
                j.set_drive_target.assert_not_called()
                j.set_drive_property.assert_not_called()
            main.get_qpos.return_value=[.015,.024]
            rig.freeze(4)
            self.assertAlmostEqual(joints[0].set_limits.call_args.args[0][0][1],.01501)
            self.assertAlmostEqual(joints[1].set_limits.call_args.args[0][0][1],.02401)
            rig.secondary.get_active_joints.assert_not_called()

    def test_closed_joint_has_positive_width_and_original_upper_is_respected(self):
        self.assertEqual(ratchet_upper(0,.04765,1e-5),1e-5)
        self.assertEqual(ratchet_upper(.04765,.04765,1e-5),.04765)

    def test_gamepad_toggle_preserves_joint_state_and_signal_source(self):
        from xbox_gamepad_physics.state import XBOX_ONE_S_CHANNELS
        switch=GamepadSwitch.__new__(GamepadSwitch)
        art=Mock();art.root.joint.type='fixed'
        pad=Mock();pad.articulation=art
        state=Mock();state.channel.side_effect=lambda name: .6 if name=='south' else 0
        pad.gamepad_state.return_value=state
        switch.active=pad;pad.root_fixed=True
        expected={'from':'fixed','to':'moving','pose':[0,0,.03,1,0,0,0],
                  'joint_positions':{'a_press':.001},'drive_targets':{'a_press':0},
                  'signal_delta':dict.fromkeys(XBOX_ONE_S_CHANNELS,0)}
        pad.set_root_fixed.return_value=expected
        self.assertIs(switch.toggle(),expected)
        pad.set_root_fixed.assert_called_once_with(False)
        self.assertIs(switch.last_transition,expected)
        self.assertIs(switch.active,pad)
        art.set_qpos.assert_not_called();art.set_qvel.assert_not_called()
        art.set_root_pose.assert_not_called();art.root.wake_up.assert_not_called()
        self.assertEqual(art.root.joint.type,'fixed')
        pad.root_fixed=False
        switch.toggle();pad.set_root_fixed.assert_called_with(True)


class ReplayConfigurationTest(unittest.TestCase):
    def test_small_limit_margin_remains_numeric_in_registered_entry(self):
        from pathlib import Path
        import tempfile
        from experiments.runner import load_config
        from teleop.acceptance import write_replay_config
        config={'teleop':{'freeze':{'limit_margin_m':1e-5}}}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.yaml'
            write_replay_config(path,{'config':config},Path('record.jsonl'))
            actual=load_config(path)
        self.assertEqual(actual['teleop'],config['teleop'])
