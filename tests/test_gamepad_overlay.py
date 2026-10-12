import hashlib
import importlib.util
import json
import math
import subprocess
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "generate_gamepad_overlay_demo",
    ROOT / "scripts" / "generate_gamepad_overlay_demo.py",
)
demo = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(demo)


class GamepadOverlayDemoTests(unittest.TestCase):
    def test_trace_uses_controller_output_and_completes_one_circle(self):
        trace = demo.build_trace(fps=10)
        self.assertEqual(trace["frame_count"], 62)
        self.assertAlmostEqual(trace["duration_seconds"], 6.2)
        self.assertLess(trace["maximum_radius_error"], 1e-12)

        circle = [
            frame for frame in trace["frames"]
            if frame["telemetry"]["phase"] == "circle"
        ]
        self.assertEqual(len(circle), 40)
        for frame in circle:
            self.assertEqual(sum(frame["available_mask"]), 2)
            self.assertEqual(sum(frame["task_mask"]), 2)
            self.assertAlmostEqual(math.hypot(frame["values"][0], frame["values"][1]), 1.0)
        self.assertAlmostEqual(circle[0]["values"][0], 1.0)
        self.assertAlmostEqual(circle[0]["values"][1], 0.0)
        self.assertAlmostEqual(circle[-1]["values"][0], 1.0)
        self.assertAlmostEqual(circle[-1]["values"][1], 0.0, places=12)

    def test_distributed_overlay_files_match_recorded_hashes(self):
        if not (ROOT / '.git').exists():
            self.skipTest('运行镜像不含HEAD历史；overlay来源和补丁哈希在本地checkout验证')
        directory = ROOT / "viewer" / "gamepad_overlay"
        provenance = json.loads((directory / "upstream.json").read_text())
        self.assertEqual(
            provenance["revision"],
            "31236cd6a029828c8b01966ddc1a92c31e5cd852",
        )
        original = json.loads(subprocess.check_output(
            ["git", "show", "HEAD:viewer/gamepad_overlay/upstream.json"], cwd=ROOT
        ))
        for key in ("repository", "revision", "license", "files", "retrieved_at", "local_modifications"):
            self.assertEqual(provenance[key], original[key], key)
        # Keep the original distribution record; apply explicit local patches
        # in order instead of silently replacing its file hashes.
        expected_hashes = dict(provenance["files"])
        # Project-owned adapter/theme have no upstream-distribution hash.
        # Their immutable starting bytes are tracked separately, then patched.
        for relative, expected in provenance.get("project_adapter_files", {}).items():
            baseline = subprocess.check_output(["git", "show", "HEAD:viewer/gamepad_overlay/" + relative], cwd=ROOT)
            self.assertEqual(hashlib.sha256(baseline).hexdigest(), expected)
            expected_hashes[relative] = expected
        for patch in provenance.get("local_patches", []):
            self.assertTrue(patch["id"])
            self.assertRegex(patch["date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(patch["reason"])
            for relative, record in patch["files"].items():
                self.assertEqual(record["before_sha256"], expected_hashes[relative])
                self.assertTrue(record["reason"])
                expected_hashes[relative] = record["sha256"]
        for relative, expected_hash in expected_hashes.items():
            with self.subTest(relative=relative):
                actual_hash = hashlib.sha256((directory / relative).read_bytes()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)


if __name__ == "__main__":
    unittest.main()
