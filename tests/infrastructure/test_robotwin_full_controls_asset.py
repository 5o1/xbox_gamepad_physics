import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for path in (SRC, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_robotwin_full_controls import build  # noqa: E402
from xbox_gamepad_physics.robotwin.loader import _validated_description  # noqa: E402


PROFILE = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "robotwin"
    / "full_controls"
)


class RoboTwinFullControlsAssetTest(unittest.TestCase):
    def test_generated_profile_is_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory)
            build(generated)
            expected = sorted(
                path.relative_to(PROFILE)
                for path in PROFILE.rglob("*")
                if path.is_file()
            )
            actual = sorted(
                path.relative_to(generated)
                for path in generated.rglob("*")
                if path.is_file()
            )
            self.assertEqual(actual, expected)
            for relative in expected:
                self.assertEqual(
                    (generated / relative).read_bytes(),
                    (PROFILE / relative).read_bytes(),
                    relative,
                )

    def test_joint_tree_and_controller_cover_all_device_controls(self):
        root = ET.parse(PROFILE / "mobility.urdf").getroot()
        links = root.findall("link")
        joints = root.findall("joint")
        self.assertEqual(len(links), 21)
        self.assertEqual(len(joints), 20)
        self.assertEqual(
            sum(joint.get("type") == "prismatic" for joint in joints), 12
        )
        self.assertEqual(
            sum(joint.get("type") == "revolute" for joint in joints), 8
        )
        self.assertTrue(all(link.find("inertial") is not None for link in links))

        description = _validated_description("full_controls")
        controller = description.signal_controller
        self.assertEqual(len(description.joint_dynamics), 20)
        self.assertEqual(len(controller.available_channels), 21)
        self.assertEqual(len(set(controller.available_channels)), 21)
        self.assertEqual(len(controller.physical_event_mappings), 1)

    def test_isolated_joint_endpoints_produce_named_signals(self):
        description = _validated_description("full_controls")
        controller = description.signal_controller
        positions = {item.name: 0.0 for item in description.joint_dynamics}

        expected = {}
        for mapping in controller.axis_mappings:
            sample = dict(positions)
            sample[mapping.source] = mapping.upper
            expected[mapping.channel] = controller.encode(sample).channel(mapping.channel)
        for mapping in controller.scalar_mappings:
            sample = dict(positions)
            sample[mapping.source] = mapping.upper
            expected[mapping.channel] = controller.encode(sample).channel(mapping.channel)
        for mapping in controller.split_mappings:
            positive = dict(positions)
            positive[mapping.source] = mapping.upper
            negative = dict(positions)
            negative[mapping.source] = mapping.lower
            expected[mapping.positive_channel] = controller.encode(positive).channel(
                mapping.positive_channel
            )
            expected[mapping.negative_channel] = controller.encode(negative).channel(
                mapping.negative_channel
            )

        self.assertEqual(set(expected), set(controller.available_channels))
        for channel, value in expected.items():
            with self.subTest(channel=channel):
                self.assertAlmostEqual(value, 1.0)

        event = controller.physical_event_mappings[0]
        positions[event.source] = event.upper
        self.assertEqual(
            controller.encode_physical_events(positions),
            {"pair_bind_connect": 1.0},
        )

    def test_mass_budget_matches_whole_controller_estimate(self):
        collision = json.loads((PROFILE / "collision" / "manifest.json").read_text())
        self.assertAlmostEqual(sum(collision["mass_kg"].values()), 0.28, places=12)

if __name__ == "__main__":
    unittest.main()
