from __future__ import annotations

import json
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
    / "left_stick_estimated_v0"
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
        profile = require_physics_ready("robotwin", "left_stick_estimated_v0")
        self.assertTrue(profile.physics_ready)
        description = _validated_description("left_stick_estimated_v0")
        self.assertEqual(
            tuple(item.name for item in description.joint_dynamics),
            ("left_stick_x", "left_stick_y"),
        )
        self.assertEqual(
            tuple(item.channel for item in description.axis_mappings),
            ("left_x", "left_y"),
        )
        self.assertEqual(
            description.radial_groups[0].channels, ("left_x", "left_y")
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

    def test_recorded_sapien_contact_run_moves_and_releases_stick(self):
        result = json.loads(
            (ROOT / "results" / "robotwin_left_stick_estimated_v0" / "result.json").read_text()
        )
        self.assertEqual(result["sapien"], "3.0.0b1")
        self.assertAlmostEqual(
            result["samples"]["diagonal_joint_corner"]["signal_radius"], 1.0
        )
        probe = result["contact_probe"]
        self.assertGreater(probe["contact_frames"], 0)
        self.assertGreater(probe["peak_abs_left_stick_x_rad"], 0.25)
        self.assertLess(abs(probe["released_qpos"]["left_stick_x"]), 1e-6)
        sensitivity = json.loads(
            (ROOT / "results" / "robotwin_left_stick_estimated_v0" / "sensitivity.json").read_text()
        )
        self.assertEqual(sensitivity["case_count"], 27)
        self.assertTrue(sensitivity["passed"])
        self.assertTrue(all(item["passed"] for item in sensitivity["cases"]))
        video = (
            ROOT
            / "results"
            / "robotwin_left_stick_estimated_v0"
            / "render"
            / "left_stick_contact_probe.mp4"
        )
        self.assertGreater(video.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
