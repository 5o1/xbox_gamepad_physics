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

from build_mujoco_full_controls import build  # noqa: E402
from xbox_gamepad_physics.mujoco._manifest import load_runtime_manifest  # noqa: E402


PROFILE = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "mujoco"
    / "full_controls_estimated_v0"
)


class MujocoFullControlsAssetTest(unittest.TestCase):
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

    def test_mjcf_declares_complete_named_mechanism(self):
        root = ET.parse(PROFILE / "xbox_one_s.xml").getroot()
        self.assertEqual(len(root.findall(".//joint")), 20)
        self.assertEqual(len(root.findall(".//sensor/jointpos")), 20)
        self.assertEqual(len(root.findall(".//geom[@type='mesh']")), 16)
        self.assertGreater(len(root.findall(".//geom[@group='0']")), 20)
        self.assertEqual(len(root.findall(".//keyframe/key")), 1)

    def test_runtime_manifest_builds_shared_signal_controller(self):
        manifest = load_runtime_manifest("full_controls_estimated_v0")
        self.assertEqual(len(manifest.joints), 20)
        self.assertEqual(len(manifest.sensors), 20)
        self.assertIsNotNone(manifest.signal_controller)
        self.assertEqual(len(manifest.signal_controller.available_channels), 21)
        self.assertEqual(len(manifest.signal_controller.physical_event_mappings), 1)

    def test_recorded_nonvisual_mujoco_run_covers_full_interface(self):
        result = json.loads(
            (
                ROOT / "results" / "mujoco_full_controls_estimated_v0" / "result.json"
            ).read_text()
        )
        self.assertEqual(result["joint_count"], 20)
        self.assertEqual(result["sensor_count"], 20)
        self.assertEqual(result["available_game_channels"], 21)
        self.assertEqual(len(result["endpoint_checks"]), 21)
        self.assertEqual(min(result["endpoint_checks"].values()), 1.0)
        self.assertEqual(result["physical_events"], {"pair_bind_connect": 1.0})
        self.assertLess(result["command_roundtrip_max_error"], 1e-12)
        self.assertLess(result["pair_roundtrip_error"], 1e-12)
        self.assertEqual(result["initial_contacts"], [])
        self.assertLess(result["return_final_l1"], 1e-3)
        self.assertTrue(result["finite"])

    def test_recorded_left_stick_contact_moves_and_releases(self):
        result = json.loads(
            (
                ROOT
                / "results"
                / "mujoco_full_controls_estimated_v0"
                / "contact_result.json"
            ).read_text()
        )
        self.assertGreater(result["contact_frames"], 0)
        self.assertGreater(result["peak_abs_left_x"], 0.5)
        self.assertGreater(result["peak_abs_left_stick_x_rad"], 0.2)
        self.assertLess(abs(result["released_left_stick_x_rad"]), 1e-6)
        self.assertLess(abs(result["released_left_stick_y_rad"]), 1e-6)
        self.assertTrue(result["finite"])


if __name__ == "__main__":
    unittest.main()
