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


PACKAGED = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "common"
    / "xbox_one_s"
    / "motion"
    / "full_controls.json"
)


class CommonMotionAssetTest(unittest.TestCase):
    def test_packaged_contract_is_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "full_controls.json"
            build(generated)
            self.assertEqual(generated.read_bytes(), PACKAGED.read_bytes())

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
