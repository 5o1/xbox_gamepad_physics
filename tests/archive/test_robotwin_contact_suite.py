import importlib.util
import json
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "render_robotwin_sphere_contact_suite",
    ROOT / "scripts/archive/render_robotwin_sphere_contact_suite.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RobotwinContactSuiteTest(unittest.TestCase):
    def test_cases_cover_requested_controls_and_resolve_asset_names(self):
        cases = MODULE.CONTACT_CASES
        self.assertEqual(len(cases), 19)
        self.assertEqual(len({case.key for case in cases}), len(cases))
        self.assertEqual(
            {case.group for case in cases},
            {"sticks", "buttons", "dpad", "shoulders", "triggers"},
        )
        motion = json.loads(
            (ROOT / "src/xbox_gamepad_physics/resource_data/common/xbox_one_s/motion/full_controls.json").read_text()
        )
        collision = json.loads(
            (ROOT / "src/xbox_gamepad_physics/resource_data/robotwin/full_controls/collision/manifest.json").read_text()
        )
        urdf = ET.parse(
            ROOT / "src/xbox_gamepad_physics/resource_data/robotwin/full_controls/mobility.urdf"
        ).getroot()
        joints = {item.get("name") for item in urdf.findall("joint")}
        channels = {
            item["channel"]
            for group in ("axes", "scalars")
            for item in motion["bindings"][group]
        }
        channels.update(
            name
            for item in motion["bindings"]["splits"]
            for name in (item["negative_channel"], item["positive_channel"])
        )
        for case in cases:
            with self.subTest(case=case.key):
                self.assertIn(case.joint, joints)
                self.assertIn(case.link, collision["links"])
                self.assertIn(case.channel, channels)

    def test_recorded_motion_starts_releases_and_never_commands_state(self):
        counts = {"lead": 4, "push": 12, "hold": 6, "release": 12}
        total = sum(counts.values())
        self.assertEqual(MODULE.frame_phase(0, **counts), ("ready", 0.0))
        self.assertEqual(MODULE.frame_phase(total - 1, **counts), ("release / passive return", 0.0))
        source = (ROOT / "scripts/archive/render_robotwin_sphere_contact_suite.py").read_text()
        self.assertNotIn("set_gamepad_targets(", source)
        self.assertNotIn("set_gamepad_state(", source)


if __name__ == "__main__":
    unittest.main()
