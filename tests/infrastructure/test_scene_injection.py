"""The caller-owned scene insertion gate; requires the real SAPIEN backend."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(importlib.util.find_spec("sapien"), "SAPIEN is not installed")
class SceneInjectionTest(unittest.TestCase):
    def test_existing_scene_is_preserved(self):
        script = Path(__file__).with_name("scene_injection_probe.py")
        for shader in ("default", "rt"):
            with self.subTest(shader=shader):
                completed = subprocess.run([sys.executable, str(script), "--shader", shader],
                    check=False, capture_output=True, text=True, env=os.environ.copy())
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                result = json.loads(completed.stdout)
                self.assertTrue(result["settings_equal"], result)
                self.assertTrue(result["physics_exact"], result)
                if shader == "default":
                    self.assertEqual(result["insertion"]["outside_changed_pixels"], 0, result)
                    self.assertEqual(result["insertion"]["outside_raw_float_changed_pixels"], 0, result)
