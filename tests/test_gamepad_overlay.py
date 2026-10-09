import hashlib
import importlib.util
import json
import math
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
        directory = ROOT / "viewer" / "gamepad_overlay"
        provenance = json.loads((directory / "upstream.json").read_text())
        self.assertEqual(
            provenance["revision"],
            "31236cd6a029828c8b01966ddc1a92c31e5cd852",
        )
        for relative, expected_hash in provenance["files"].items():
            with self.subTest(relative=relative):
                actual_hash = hashlib.sha256((directory / relative).read_bytes()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)


if __name__ == "__main__":
    unittest.main()
