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
        self.assertNotIn("mujoco/full_controls: ready", rendered)

    def test_status_json_is_machine_readable(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["status", "--backend", "robotwin", "--json"])
        self.assertEqual(status, 0)
        self.assertIn('"physics_ready": true', output.getvalue())

    def test_verify_accepts_default_full_controls(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["verify", "--backend", "all"])
        self.assertEqual(status, 0)
        self.assertIn("robotwin/full_controls: ready", output.getvalue())
        self.assertNotIn("mujoco/full_controls: ready", output.getvalue())

    def test_mujoco_explicit_selection_reports_release_scope(self):
        for command in ("status", "verify"):
            errors = io.StringIO()
            with redirect_stderr(errors):
                result = main([command, "--backend", "mujoco"])
            self.assertEqual(result, 2)
            self.assertIn("mujoco backend builder is not implemented in C1", errors.getvalue())

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
