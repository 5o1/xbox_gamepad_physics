"""Catch imports accidentally satisfied by stale build/lib payloads."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.infrastructure.review_release_wheel import stale_imports
from xbox_gamepad_physics.teleop.record import finite


class PackagedEntrypointsTest(unittest.TestCase):
    def test_gateway_help(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
        result = subprocess.run(
            [sys.executable, "-m", "xbox_gamepad_physics.teleop.stream.gateway", "--help"],
            env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checkout-only sphere contact experiment", result.stdout)

    def test_source_does_not_import_stale_wheel_modules(self):
        self.assertEqual(stale_imports()["hits"], [])

    def test_import_scan_resolves_relative_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "src/xbox_gamepad_physics/teleop/stream/probe.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "from .. import ball_probe\n"
                "from ..finger_validate import finite\n"
                "from teleop.ball_probe import CASES\n"
                "names = ['xbox_gamepad_physics.teleop.validate']\n")
            self.assertEqual([hit["module"] for hit in stale_imports(root)["hits"]], [
                "xbox_gamepad_physics.teleop.ball_probe",
                "xbox_gamepad_physics.teleop.finger_validate"])

    def test_nested_record_finite_values(self):
        self.assertTrue(finite({"q": [0.0, (1, None, "rest")], "active": True}))
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertFalse(finite({"q": [0.0, (1, value)]}))


if __name__ == "__main__":
    unittest.main()
