from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_robotwin_left_stick import build  # noqa: E402
from xbox_gamepad_physics.profiles import require_physics_ready  # noqa: E402
from xbox_gamepad_physics.robotwin.loader import _validated_description  # noqa: E402


PROFILE = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "robotwin"
    / "left_stick"
)


class RoboTwinLeftStickAssetTest(unittest.TestCase):
    def test_generated_profile_is_fresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary)
            build(generated)
            expected = sorted(path.relative_to(PROFILE) for path in PROFILE.rglob("*") if path.is_file())
            actual = sorted(path.relative_to(generated) for path in generated.rglob("*") if path.is_file())
            self.assertEqual(actual, expected)
            for relative in expected:
                self.assertEqual(
                    (generated / relative).read_bytes(),
                    (PROFILE / relative).read_bytes(),
                    relative,
                )

    def test_ready_profile_and_loader_description_match_asset(self):
        profile = require_physics_ready("robotwin", "left_stick")
        self.assertTrue(profile.physics_ready)
        description = _validated_description("left_stick")
        self.assertEqual(
            tuple(item.name for item in description.joint_dynamics),
            ("left_stick_x", "left_stick_y"),
        )
        self.assertEqual(
            tuple(
                item.channel
                for item in description.signal_controller.axis_mappings
            ),
            ("left_x", "left_y"),
        )
        self.assertEqual(
            description.signal_controller.radial_groups[0].channels,
            ("left_x", "left_y"),
        )

    def test_urdf_contains_explicit_physics_and_contact_geometry(self):
        root = ET.parse(PROFILE / "mobility.urdf").getroot()
        links = {link.get("name"): link for link in root.findall("link")}
        self.assertEqual(
            set(links), {"controller_body", "left_stick_x_frame", "left_stick"}
        )
        for link in links.values():
            self.assertIsNotNone(link.find("inertial/origin"))
            self.assertGreater(float(link.find("inertial/mass").get("value")), 0)
        self.assertEqual(len(links["controller_body"].findall("collision")), 17)
        self.assertEqual(len(links["left_stick"].findall("collision")), 3)
        joints = {joint.get("name"): joint for joint in root.findall("joint")}
        self.assertEqual(set(joints), {"left_stick_x", "left_stick_y"})
        for joint in joints.values():
            limit = joint.find("limit")
            self.assertAlmostEqual(float(limit.get("lower")), -0.401425727959)
            self.assertAlmostEqual(float(limit.get("upper")), 0.401425727959)
            self.assertIsNotNone(joint.find("dynamics"))

if __name__ == "__main__":
    unittest.main()
