from unittest import mock
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_common_motion import build  # noqa: E402
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.backends.common.constraints import ShaftTiltLimit
from xbox_gamepad_physics import load_motion_contract  # noqa: E402


class CommonMotionAssetTest(unittest.TestCase):
    def test_generated_contract_loads_and_covers_named_joints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "common/xbox_one_s/motion/full_controls.json"
            contract = build(generated)
            with mock.patch("xbox_gamepad_physics.resources.resource_root", return_value=root):
                motion = load_motion_contract("full_controls")
            self.assertEqual(set(motion.joint_by_name), {item["name"] for item in contract["joints"]})
            self.assertEqual(len(motion.joints), 20)
            self.assertEqual(len(motion.signal_controller.available_channels), 21)
            self.assertEqual(len(motion.signal_controller.physical_event_mappings), 1)

    def test_owner_selected_radial_deadzone_clears_residual_without_rescaling(self):
        motion = load_motion_contract("full_controls")
        controller = motion.signal_controller
        self.assertEqual([g.neutral_epsilon for g in controller.radial_groups], [.02, .02])
        for side in ("left", "right"):
            x, y = side + "_stick_x", side + "_stick_y"
            limits = motion.joint_by_name
            def encoded(nx, ny):
                q = {j.name: 0.0 for j in motion.joints}
                q[x], q[y] = nx * limits[x].upper, ny * limits[y].upper
                return controller.encode(q)
            for nx, ny in ((.01013, 0), (.012, .016)):
                state = encoded(nx, ny)
                self.assertEqual(state.channel(side + "_x"), 0)
                self.assertEqual(state.channel(side + "_y"), 0)
            state = encoded(.021, .004)
            self.assertAlmostEqual(state.channel(side + "_x"), .021)
            self.assertAlmostEqual(state.channel(side + "_y"), .004)

    def test_circular_mechanical_limit_is_separate_from_signal_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = build(Path(directory) / "motion.json")
        motion = motion_from_dict(raw)
        limits = {item["id"]: item for item in motion.joint_space_constraints
                  if item["type"] == "shaft_tilt_limit"}
        self.assertEqual(set(limits), {"left_stick_circular_limit", "right_stick_circular_limit"})
        for side in ("left", "right"):
            limit = limits[f"{side}_stick_circular_limit"]
            self.assertEqual(limit["reference_link"], "controller_body")
            self.assertEqual(limit["moving_link"], f"{side}_stick_y_frame")
            self.assertEqual(limit["independent_of"], [f"{side}_stick_click"])
            self.assertAlmostEqual(limit["max_angle_rad"], motion.joint_by_name[f"{side}_stick_x"].upper)
            self.assertEqual(limit["coordinate_space"], "relative_shaft_direction")
            self.assertEqual(limit["enforcement"], "hard")
            self.assertEqual(limit["on_unsupported"], "error")
            self.assertIn("each_physics_substep", limit["required_stages"])
            self.assertIs(limit["signal_projection_is_enforcement"], False)
            self.assertEqual(limit["reference_axis"], [0.0, 0.0, 1.0])
            self.assertEqual(limit["moving_axis"], [0.0, 0.0, 1.0])
        self.assertEqual(len([c for c in motion.joint_space_constraints if c["type"] == "radial"]), 3)
        self.assertEqual(len(motion.joints), 20)
        self.assertEqual(len(motion.signal_controller.available_channels), 21)

    def test_public_contract_owns_ranges_and_signal_constraints(self):
        motion = load_motion_contract("full_controls")
        self.assertEqual(len(motion.joints), 20)
        self.assertEqual(len(motion.signal_controller.available_channels), 21)
        for name in ("left_stick_x", "left_stick_y", "right_stick_x", "right_stick_y"):
            joint = motion.joint_by_name[name]
            self.assertAlmostEqual(joint.lower, -0.4014257279586958)
            self.assertAlmostEqual(joint.upper, 0.4014257279586958)
        for name in ("dpad_horizontal", "dpad_vertical"):
            joint = motion.joint_by_name[name]
            self.assertAlmostEqual(joint.lower, -0.17453241348266602)
            self.assertAlmostEqual(joint.upper, 0.17453241348266602)

    def test_shaft_limit_values_are_engine_independent_and_accept_existing_records(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = build(Path(directory) / "motion.json")
        record = next(item for item in raw['joint_space_constraints']
                      if item['type'] == 'shaft_tilt_limit')
        parsed = ShaftTiltLimit.from_record(record)
        minimal = {key: record[key] for key in ('type', 'enforcement', 'id', 'reference_link',
            'moving_link', 'reference_axis', 'moving_axis', 'max_angle_rad')}
        self.assertEqual(ShaftTiltLimit.from_record(minimal), parsed)
        for changes in ({'max_angle_rad': float('nan')}, {'max_angle_rad': True},
                        {'reference_axis': [0., 0., 0.]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ShaftTiltLimit.from_record({**minimal, **changes})


if __name__ == "__main__":
    unittest.main()
