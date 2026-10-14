"""Schema-5 finger commands ramp at each physics boundary, without SAPIEN."""
import copy
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import yaml

from teleop.gripper import (GripperRig, advance_finger_target, validate_finger_speed,
                            finger_velocity_settings, validate_finger_velocity_drive)
from teleop.inputs import Inputs
from teleop.session import command_target

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / 'configs/teleop_gripper.yaml').read_text())
DT = .004
SPEED = .05
POSE = [0, 0, .2, 1, 0, 0, 0]


def articulation(qpos):
    art = Mock()
    art.root.joint.type = 'free'
    art.get_root_pose.return_value = SimpleNamespace(p=np.array(POSE[:3]), q=np.array(POSE[3:]))
    art.get_root_linear_velocity.return_value = np.zeros(3)
    art.get_root_angular_velocity.return_value = np.zeros(3)
    art.get_qpos.return_value = qpos
    art.get_qvel.return_value = [0., 0.]
    joints = []
    for name in ('fl_joint7', 'fl_joint8'):
        joint = Mock()
        joint.name = name
        joint.get_drive_target.return_value = [-.002]
        joints.append(joint)
    art.get_active_joints.return_value = joints
    return art


def rig(schema=5):
    result = GripperRig.__new__(GripperRig)
    result.cfg = copy.deepcopy(CFG['teleop'])
    result.schema_version = schema
    result.main = articulation([.034, .036])
    result.secondary = articulation([.02, .02])
    result.scene = Mock()
    result.scene.get_timestep.return_value = DT
    result.target = list(POSE)
    result.finger_target = -.002
    result.finger_drive_targets = {'main': .035, 'secondary': .02}
    result.entities = {'secondary': [Mock()]}
    result.inactive_data = {}
    result.original_limits = {name: [[0, .04765]] for name in ('fl_joint7', 'fl_joint8')}
    result.frozen = None
    result.initialize = Mock()
    result.set_groups = Mock()
    return result


class FingerVelocityTest(unittest.TestCase):
    def test_physics_step_increment_reaches_target_and_stops(self):
        current = .04765
        for step in range(249):
            after = advance_finger_target(current, -.002, SPEED, DT)
            self.assertLessEqual(abs(after-current), SPEED*DT+1e-15)
            self.assertAlmostEqual(after, max(-.002, .04765-(step+1)*SPEED*DT), places=13)
            current = after
        self.assertEqual(current, -.002)
        for _ in range(10):
            self.assertEqual(advance_finger_target(current, -.002, SPEED, DT), -.002)
        self.assertEqual(advance_finger_target(.02, .02, SPEED, DT), .02)

    def test_reversal_immediately_changes_direction_without_target_jump(self):
        current = advance_finger_target(.02, -.002, SPEED, DT)
        self.assertAlmostEqual(current, .0198)
        reversed_target = advance_finger_target(current, .04765, SPEED, DT)
        self.assertAlmostEqual(reversed_target, .02)
        self.assertEqual(advance_finger_target(current, .0199, SPEED, DT), .0199)

    def test_click_and_coarse_fine_wheel_commands_share_same_ramp(self):
        input_cfg = CFG['teleop']['input']
        for fine in (False, True):
            for message, desired in (({'grip': 'close'}, -.002), ({'grip': 'open'}, .04765),
                                     ({'opening': -1}, .02-input_cfg['fine' if fine else 'coarse']['opening_m']),
                                     ({'opening': 1}, .02+input_cfg['fine' if fine else 'coarse']['opening_m'])):
                with self.subTest(fine=fine, message=message):
                    controls = Inputs(camera_relative=True, input_config=input_cfg,
                                      cursor_config=CFG['stream']['cursor'], schema_version=5)
                    controls.accept({'seq': 1, 'kind': 'focus'}, 0)
                    controls.accept({'seq': 2, 'kind': 'delta', 'fine': fine, **message}, 0)
                    command = controls.command(0, pose=POSE, finger_target=.02)
                    _, target = command_target(POSE, .02, command, input_cfg, dt=DT)
                    self.assertAlmostEqual(target, desired)
                    actual_drive = advance_finger_target(.02, target, SPEED, DT)
                    self.assertAlmostEqual(abs(actual_drive-.02), SPEED*DT)
                    self.assertEqual(math.copysign(1, actual_drive-.02), math.copysign(1, desired-.02))

    def test_each_finger_gets_same_ramped_drive_and_preload_command_is_preserved(self):
        gripper = rig()
        gripper.drive(gripper.main, 0)
        self.assertEqual(gripper.finger_target, -.002)
        self.assertAlmostEqual(gripper.finger_drive_targets['main'], .0348)
        for joint in gripper.main.get_active_joints():
            self.assertAlmostEqual(joint.set_drive_target.call_args.args[0], .0348)
        gripper.main.get_qpos.return_value = [.033, .035]
        gripper.drive(gripper.main, DT)
        self.assertAlmostEqual(gripper.finger_drive_targets['main'], .0346)

    def test_freeze_secondary_birth_and_restore_rebase_from_actual_positions(self):
        gripper = rig()
        gripper.finger_drive_targets['main'] = .005
        with patch('teleop.gripper.articulation_data', return_value={}):
            gripper.freeze(1)
            gripper.initialize.assert_called_once_with(gripper.secondary, POSE, [.034, .036])
            self.assertAlmostEqual(gripper.finger_drive_targets['main'], .035)
            self.assertAlmostEqual(gripper.finger_drive_targets['secondary'], .035)
            self.assertAlmostEqual(gripper.finger_target, .035)
            self.assertEqual(gripper.frozen['finger_command_target_m'], -.002)
            gripper.main.get_qpos.return_value = [.030, .032]
            gripper.finger_drive_targets['main'] = .010
            gripper.restore(2)
        self.assertAlmostEqual(gripper.finger_drive_targets['main'], .031)
        self.assertEqual(gripper.finger_target, -.002)
        gripper.drive(gripper.main, 2)
        self.assertAlmostEqual(gripper.finger_drive_targets['main'], .0308)
        gripper.main.set_qpos.assert_not_called()

    def test_schema_three_and_four_keep_instant_finger_targets(self):
        for schema in (3, 4):
            with self.subTest(schema=schema):
                gripper = rig(schema)
                gripper.drive(gripper.main, 0)
                for joint in gripper.main.get_active_joints():
                    self.assertEqual(joint.set_drive_target.call_args.args[0], -.002)
                with patch('teleop.gripper.articulation_data', return_value={}):
                    gripper.freeze(1)
                    gripper.restore(2)
                self.assertEqual(gripper.finger_target, -.002)

    def test_frozen_main_continues_its_preload_ramp_independently_of_secondary(self):
        gripper = rig()
        with patch('teleop.gripper.articulation_data', return_value={}):
            gripper.freeze(1)
        gripper.finger_target = .04765
        gripper.drive(gripper.secondary, 1)
        self.assertAlmostEqual(gripper.finger_drive_targets['main'], .0348)
        self.assertAlmostEqual(gripper.finger_drive_targets['secondary'], .0352)
        for art, expected in ((gripper.main, .0348), (gripper.secondary, .0352)):
            for joint in art.get_active_joints():
                self.assertAlmostEqual(joint.set_drive_target.call_args.args[0], expected)

    def test_config_speed_has_units_and_respects_contact_offset_boundary(self):
        self.assertEqual(CFG['teleop']['finger_drive']['speed_m_s'], SPEED)
        validate_finger_speed(CFG['teleop'], DT)
        for speed, dt, offset in ((.050001, DT, .0002), (SPEED, .004001, .0002),
                                  (SPEED, DT, .000199)):
            with self.subTest(speed=speed, dt=dt, offset=offset):
                cfg = copy.deepcopy(CFG['teleop'])
                cfg['finger_drive']['speed_m_s'] = speed
                cfg['contact_offset_m'] = offset
                with self.assertRaises(ValueError):
                    validate_finger_speed(cfg, dt)
        for speed in (0, -SPEED, math.nan, math.inf):
            cfg = copy.deepcopy(CFG['teleop'])
            cfg['finger_drive']['speed_m_s'] = speed
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                validate_finger_speed(cfg, DT)

    def test_float32_timestep_passes_but_one_percent_extra_speed_is_rejected(self):
        dt = float(np.float32(DT))
        self.assertGreater(SPEED * dt, CFG["teleop"]["contact_offset_m"])
        validate_finger_speed(CFG["teleop"], dt)
        cfg = copy.deepcopy(CFG["teleop"])
        cfg["finger_drive"]["speed_m_s"] = SPEED * 1.01
        with self.assertRaisesRegex(ValueError, "contact_offset_m"):
            validate_finger_speed(cfg, dt)

    def test_invalid_config_is_rejected_at_session_load_before_scene_setup(self):
        from teleop.runtime import make_session
        cfg = copy.deepcopy(CFG)
        cfg['teleop']['finger_drive']['speed_m_s'] = .051
        with patch('teleop.site.resolve_config') as resolve:
            with self.assertRaisesRegex(ValueError, 'contact_offset_m'):
                make_session(cfg, '/tmp/teleop_h_invalid_config_unused')
        resolve.assert_not_called()


class ActualFingerVelocityTest(unittest.TestCase):
    def test_velocity_mode_has_no_spring_and_reaches_eight_n_when_blocked(self):
        settings = finger_velocity_settings(.04, -.002, CFG['teleop']['finger_drive'], DT)
        self.assertEqual(settings['stiffness_n_m'], 0)
        self.assertEqual(settings['velocity_target_m_s'], -.05)
        self.assertEqual(settings['position_target_m'], .04)
        self.assertEqual(abs(settings['damping_ns_m']*settings['velocity_target_m_s']), 8)
        self.assertEqual(settings['force_limit_n'], 8)

    def test_blocking_does_not_accumulate_target_and_reversal_uses_actual_q(self):
        gripper = rig(6)
        gripper.finger_drives = {'main': {}, 'secondary': {}}
        for _ in range(100):
            gripper.drive_fingers(gripper.main, 'main', -.002)
        for name, actual in zip(('fl_joint7', 'fl_joint8'), (.034, .036)):
            self.assertEqual(gripper.finger_drives['main'][name]['position_target_m'], actual)
            self.assertEqual(gripper.finger_drives['main'][name]['velocity_target_m_s'], -.05)
        gripper.drive_fingers(gripper.main, 'main', .04765)
        for settings in gripper.finger_drives['main'].values():
            self.assertEqual(settings['velocity_target_m_s'], .05)

    def test_same_command_independent_actual_positions_and_hold(self):
        gripper = rig(6)
        gripper.finger_drives = {'main': {}, 'secondary': {}}
        gripper.drive_fingers(gripper.main, 'main', .035)
        settings = gripper.finger_drives['main']
        self.assertEqual(settings['fl_joint7']['velocity_target_m_s'], .05)
        self.assertEqual(settings['fl_joint8']['velocity_target_m_s'], -.05)
        for actual in (.035, .0349, .0351):
            hold = finger_velocity_settings(actual, .035, CFG['teleop']['finger_drive'], DT)
            self.assertEqual(hold['mode'], 'position_hold')
            self.assertEqual(hold['velocity_target_m_s'], 0)
            self.assertEqual(hold['position_target_m'], .035)
            self.assertEqual(hold['stiffness_n_m'], 1800)
            self.assertEqual(hold['damping_ns_m'], 12)

    def test_all_clicks_and_wheel_inputs_select_velocity_from_actual(self):
        cfg = CFG['teleop']['input']
        for fine in (False, True):
            for message in ({'grip': 'close'}, {'grip': 'open'}, {'opening': 1}, {'opening': -1}):
                controls = Inputs(camera_relative=True, input_config=cfg,
                                  cursor_config=CFG['stream']['cursor'], schema_version=6)
                controls.accept({'seq': 1, 'kind': 'focus'}, 0)
                controls.accept({'seq': 2, 'kind': 'delta', 'fine': fine, **message}, 0)
                command = controls.command(0, pose=POSE, finger_target=.02)
                _, target = command_target(POSE, .02, command, cfg, dt=DT)
                settings = finger_velocity_settings(.02, target, CFG['teleop']['finger_drive'], DT)
                self.assertEqual(settings['mode'], 'velocity')
                self.assertEqual(settings['velocity_target_m_s'], math.copysign(.05, target-.02))

    def test_freeze_birth_restore_rebase_each_actual_without_average_drive_error(self):
        gripper = rig(6)
        gripper.finger_drives = {'main': {}, 'secondary': {}}
        gripper.initialize.side_effect = lambda art, pose, q: setattr(art.get_qpos, 'return_value', list(q))
        with patch('teleop.gripper.articulation_data', return_value={}):
            gripper.freeze(1)
            for role in ('main', 'secondary'):
                self.assertEqual([s['position_target_m'] for s in gripper.finger_drives[role].values()], [.034, .036])
            gripper.finger_target = .04765
            gripper.drive(gripper.secondary, 1)
            self.assertTrue(all(s['velocity_target_m_s'] == -.05 for s in gripper.finger_drives['main'].values()))
            self.assertTrue(all(s['velocity_target_m_s'] == .05 for s in gripper.finger_drives['secondary'].values()))
            gripper.main.get_qpos.return_value = [.030, .032]
            gripper.restore(2)
            self.assertEqual([s['position_target_m'] for s in gripper.finger_drives['main'].values()], [.030, .032])
        gripper.main.set_qpos.assert_not_called()
        self.assertEqual(gripper.finger_target, -.002)

    def test_motion_configuration_requires_zero_stiffness_and_blocked_preload(self):
        validate_finger_velocity_drive(CFG['teleop'])
        for field, value in (('motion_stiffness_n_m', 1), ('motion_damping_ns_m', 12),
                             ('motion_damping_ns_m', math.inf)):
            cfg = copy.deepcopy(CFG['teleop'])
            cfg['finger_drive'][field] = value
            with self.assertRaises(ValueError):
                validate_finger_velocity_drive(cfg)


if __name__ == '__main__':
    unittest.main()
