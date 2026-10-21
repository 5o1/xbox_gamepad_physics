from __future__ import annotations

import json
from unittest import mock
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_robotwin_left_stick import build  # noqa: E402
from xbox_gamepad_physics.profiles import load_profile  # noqa: E402
from xbox_gamepad_physics.robotwin.loader import _validated_description  # noqa: E402
from .built_profile_checks import check_explicit_urdf_physics, check_manifest_ranges  # noqa: E402


def _profile() -> Path:
    """The left_stick profile in the resolved resource root (built on first use)."""
    from xbox_gamepad_physics.resources import resource_root

    return resource_root() / "robotwin" / "left_stick"


def _visual_root() -> Path:
    from xbox_gamepad_physics.resources import resource_root

    return resource_root() / "common" / "xbox_one_s" / "visual"


class RoboTwinLeftStickAssetTest(unittest.TestCase):
    def test_generated_profile_loads_and_has_required_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = root / "robotwin/left_stick"
            build(generated, visual_manifest=_visual_root() / "manifest.json")
            manifest = json.loads((generated / "manifest.json").read_text())
            for relative in manifest["required_files"]:
                self.assertTrue((generated / relative).is_file(), relative)
            self.assertEqual(
                check_explicit_urdf_physics(generated / "mobility.urdf"),
                {item["name"] for item in manifest["joint_dynamics"]},
            )
            check_manifest_ranges(manifest)
            joints = ET.parse(generated / "mobility.urdf").getroot().findall("joint")
            self.assertEqual({joint.get("name") for joint in joints}, {"left_stick_x", "left_stick_y"})
            with mock.patch("xbox_gamepad_physics.resources.resource_root", return_value=root):
                description = _validated_description("left_stick")
            self.assertEqual({item.name for item in description.joint_dynamics}, {joint.get("name") for joint in joints})

    def test_ready_profile_and_loader_description_match_asset(self):
        profile = load_profile("robotwin", "left_stick")
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
        root = ET.parse(_profile() / "mobility.urdf").getroot()
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
