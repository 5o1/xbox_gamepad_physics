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


if __name__ == "__main__":
    unittest.main()
