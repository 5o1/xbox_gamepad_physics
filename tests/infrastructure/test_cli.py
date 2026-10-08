from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
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
    def test_status_reports_both_profiles_without_claiming_readiness(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["status"])
        self.assertEqual(status, 0)
        rendered = output.getvalue()
        self.assertIn("robotwin/estimated_v0: blocked", rendered)
        self.assertIn("mujoco/estimated_v0: blocked", rendered)

    def test_status_json_is_machine_readable(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["status", "--backend", "mujoco", "--json"])
        self.assertEqual(status, 0)
        self.assertIn('"physics_ready": false', output.getvalue())

    def test_verify_fails_closed_for_unfinished_physics(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            status = main(["verify", "--backend", "robotwin"])
        self.assertEqual(status, 2)
        self.assertIn("dynamics_ready=False", errors.getvalue())

    def test_verify_accepts_ready_robotwin_left_stick_profile(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(
                [
                    "verify",
                    "--backend",
                    "robotwin",
                    "--profile",
                    "left_stick_estimated_v0",
                ]
            )
        self.assertEqual(status, 0)
        self.assertIn("robotwin/left_stick_estimated_v0: ready", output.getvalue())


if __name__ == "__main__":
    unittest.main()
