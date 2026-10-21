from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xbox_gamepad_physics.cli import main  # noqa: E402


class CliTest(unittest.TestCase):
    def test_status_reports_release_backend_ready(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["status"])
        self.assertEqual(status, 0)
        rendered = output.getvalue()
        self.assertIn("robotwin/full_controls: ready", rendered)
        self.assertIn("mujoco/full_controls: blocked", rendered)
        self.assertIn("  available: true", rendered)

    def test_status_json_is_machine_readable(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["status", "--backend", "robotwin", "--json"])
        self.assertEqual(status, 0)
        self.assertIn('"physics_ready": true', output.getvalue())

    def test_verify_accepts_default_full_controls(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["verify", "--backend", "robotwin"])
        self.assertEqual(status, 0)
        self.assertIn("robotwin/full_controls: ready", output.getvalue())
        self.assertNotIn("mujoco/full_controls: ready", output.getvalue())

    def test_mujoco_status_reports_available_artifact_and_pending_acceptance(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["status", "--backend", "mujoco", "--json"])
        self.assertEqual(result, 0)
        import json
        profile, = json.loads(output.getvalue())
        self.assertEqual(profile["backend"], "mujoco")
        self.assertTrue(profile["available"])
        self.assertFalse(profile["dynamics_ready"])
        self.assertIn("mujoco_full_controls", [node["name"] for node in profile["resources"]["nodes"]])
        self.assertNotIn("robotwin_full_controls", [node["name"] for node in profile["resources"]["nodes"]])

    def test_mujoco_verify_preserves_pending_physics_gate(self):
        errors = io.StringIO()
        with redirect_stderr(errors), redirect_stdout(io.StringIO()):
            result = main(["verify", "--backend", "mujoco"])
        self.assertEqual(result, 2)
        self.assertIn("dynamics_ready=False", errors.getvalue())
        self.assertNotIn("not implemented", errors.getvalue())

    def test_verify_accepts_ready_robotwin_left_stick_profile(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(
                [
                    "verify",
                    "--backend",
                    "robotwin",
                    "--profile",
                    "left_stick",
                ]
            )
        self.assertEqual(status, 0)
        self.assertIn("robotwin/left_stick: ready", output.getvalue())


if __name__ == "__main__":
    unittest.main()
