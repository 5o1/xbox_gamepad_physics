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
    def test_status_reports_backend_entrypoints(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["status"])
        self.assertEqual(status, 0)
        rendered = output.getvalue()
        self.assertIn("robotwin/full_controls:", rendered)
        self.assertIn("mujoco/full_controls:", rendered)
        self.assertNotIn("dynamics_ready", rendered)

    def test_status_json_is_machine_readable(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["status", "--backend", "robotwin", "--json"])
        self.assertEqual(status, 0)
        self.assertIn('"entrypoint": "mobility.urdf"', output.getvalue())


    def test_mujoco_status_reports_available_artifact_and_pending_acceptance(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["status", "--backend", "mujoco", "--json"])
        self.assertEqual(result, 0)
        import json
        profile, = json.loads(output.getvalue())
        self.assertEqual(profile["backend"], "mujoco")
        self.assertNotIn("available", profile)
        self.assertNotIn("dynamics_ready", profile)
        self.assertIn("mujoco_full_controls", [node["name"] for node in profile["resources"]["nodes"]])
        self.assertNotIn("robotwin_full_controls", [node["name"] for node in profile["resources"]["nodes"]])




class DoctorTest(unittest.TestCase):
    def test_doctor_reports_actual_versions_and_missing_resources(self):
        import json
        from unittest import mock
        from xbox_gamepad_physics import integration
        from importlib import metadata
        def version(name):
            if name == 'mujoco':
                return '3.16.0+concon.sdf3689.2'
            raise metadata.PackageNotFoundError(name)
        with mock.patch.object(metadata, 'version', side_effect=version), mock.patch('xbox_gamepad_physics.resources.resource_status', return_value={'missing':['mesh.obj'],'nodes':[]}):
            stream = io.StringIO()
            with redirect_stdout(stream):
                result = main(['doctor','--backend','mujoco','--json'])
        payload = json.loads(stream.getvalue())
        self.assertEqual(result, 1)
        self.assertIn('build-resources', payload['issues'][0])
        self.assertEqual(payload['versions']['mujoco'], '3.16.0+concon.sdf3689.2')
        self.assertNotIn('runtime_ready', payload)
        self.assertNotIn('ready', payload['resources'])

    def test_doctor_accepts_current_mujoco_without_sapien(self):
        import json
        from unittest import mock
        from importlib import metadata
        def version(name):
            if name == 'mujoco':
                return '3.16.0+concon.sdf3689.2'
            raise metadata.PackageNotFoundError(name)
        with mock.patch.object(metadata, 'version', side_effect=version), mock.patch('xbox_gamepad_physics.resources.resource_status', return_value={'missing':[],'nodes':[]}):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['doctor','--backend','mujoco','--json']), 0)


if __name__ == "__main__":
    unittest.main()
