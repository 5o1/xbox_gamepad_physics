import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IntegrityGateTests(unittest.TestCase):
    def run_rejected(self, command):
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn("does not match", output)
        self.assertNotIn("No module named 'bpy'", output)

    def test_bad_model_hash_is_rejected_before_blender_import(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            bad_glb = temporary / "wrong.glb"
            bad_glb.write_bytes(b"not the reviewed model")
            self.run_rejected(
                [
                    sys.executable,
                    "-O",
                    str(ROOT / "scripts/export_xbox_one_s_visual_parts.py"),
                    "--",
                    str(bad_glb),
                    str(temporary / "export"),
                ]
            )

    def test_bad_hdri_hash_is_rejected_before_blender_import(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            candidate = temporary / "candidate"
            candidate.mkdir()
            bad_hdri = temporary / "boiler_room_4k.exr"
            bad_hdri.write_bytes(b"not the reviewed HDRI")
            self.run_rejected(
                [
                    sys.executable,
                    "-O",
                    str(ROOT / "scripts/render_reference_matched_probe.py"),
                    "--",
                    str(ROOT),
                    str(candidate),
                    str(bad_hdri),
                ]
            )


if __name__ == "__main__":
    unittest.main()
