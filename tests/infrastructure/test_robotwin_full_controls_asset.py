from unittest import mock
import importlib.util
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

BUILD_DEPS = all(importlib.util.find_spec(name) is not None for name in ("numpy", "trimesh", "coacd", "manifold3d"))
if BUILD_DEPS:
    from build_robotwin_full_controls import build  # noqa: E402
from build_common_motion import build as build_motion
from xbox_gamepad_physics.robotwin.loader import _validated_description  # noqa: E402
from .built_profile_checks import check_explicit_urdf_physics, check_manifest_ranges  # noqa: E402


def _profile() -> Path:
    """The full_controls profile in the resolved resource root (built on first use)."""
    from xbox_gamepad_physics.resources import resource_root

    return resource_root() / "robotwin" / "full_controls"


def _visual_root() -> Path:
    from xbox_gamepad_physics.resources import resource_root

    return resource_root() / "common" / "xbox_one_s" / "visual"


class RoboTwinFullControlsAssetTest(unittest.TestCase):
    @unittest.skipIf(not BUILD_DEPS, "generator requires the [build] extra: numpy, trimesh, coacd and manifold3d")
    def test_generated_profile_loads_and_matches_motion_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "robotwin/full_controls"
            motion_path = root / "common/xbox_one_s/motion/full_controls.json"
            contract = build_motion(motion_path)
            build(generated, common_motion=motion_path, visual_root=_visual_root(),
                  collision_root=_visual_root().parent / "collision")
            manifest = json.loads((generated / "manifest.json").read_text())
            for relative in manifest["required_files"]:
                self.assertTrue((generated / relative).is_file(), relative)
            self.assertEqual(
                check_explicit_urdf_physics(generated / "mobility.urdf", require_moving_meshes=True),
                {item["name"] for item in manifest["joint_dynamics"]},
            )
            check_manifest_ranges(manifest)
            joints = ET.parse(generated / "mobility.urdf").getroot().findall("joint")
            self.assertEqual({joint.get("name") for joint in joints}, {item["name"] for item in contract["joints"]})
            with mock.patch("xbox_gamepad_physics.resources.resource_root", return_value=root):
                description = _validated_description("full_controls")
            self.assertEqual(len(description.joint_dynamics), 20)
            self.assertEqual(len(description.signal_controller.available_channels), 21)

    def test_joint_tree_and_controller_cover_all_device_controls(self):
        manifest = json.loads((_profile() / "manifest.json").read_text())
        self.assertEqual(
            manifest["motion_contract"],
            "common/xbox_one_s/motion/full_controls.json",
        )
        self.assertNotIn("state_mapping", manifest)
        root = ET.parse(_profile() / "mobility.urdf").getroot()
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
        self.assertEqual(len(description.joint_motion), 20)
        self.assertEqual(len(controller.available_channels), 21)
        self.assertEqual(len(set(controller.available_channels)), 21)
        self.assertEqual(len(controller.physical_event_mappings), 1)
        self.assertEqual(
            [group.neutral_epsilon for group in controller.radial_groups],
            [0.02, 0.02],
        )
        dynamics = {item.name: item for item in description.joint_dynamics}
        for name in (
            "left_stick_x",
            "left_stick_y",
            "right_stick_x",
            "right_stick_y",
        ):
            self.assertEqual(dynamics[name].friction, 0.1)

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
        collision = json.loads((_profile() / "collision" / "manifest.json").read_text())
        self.assertAlmostEqual(sum(collision["mass_kg"].values()), 0.28, places=12)

if __name__ == "__main__":
    unittest.main()
