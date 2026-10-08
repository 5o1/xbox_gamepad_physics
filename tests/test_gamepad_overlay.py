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

    def test_checked_in_trace_and_review_artifacts_are_bound(self):
        directory = ROOT / "results" / "gamepad_overlay_left_stick_circle"
        checked_trace = json.loads((directory / "trace.json").read_text())
        self.assertEqual(checked_trace, demo.build_trace(fps=30))
        observed_trace = json.loads((directory / "observed_trace.json").read_text())
        self.assertEqual(
            observed_trace["signal_source"], "sapien_articulation_qpos_readback"
        )
        controller, mapping = demo._controller_from_manifest()
        for frame in observed_trace["frames"]:
            telemetry = frame["telemetry"]
            recomputed = controller.encode(
                {
                    mapping["left_x"].source: telemetry["left_stick_x_rad"],
                    mapping["left_y"].source: telemetry["left_stick_y_rad"],
                },
                task_channels=("left_x", "left_y"),
            )
            self.assertEqual(frame["values"], list(recomputed.values))
        result = json.loads((directory / "result.json").read_text())
        self.assertEqual(result["composition"]["overlay_position"], "lower_right")
        self.assertEqual(result["composition"]["overlay_global_alpha"], 0.72)
        self.assertIn("RoboTwin/SAPIEN", result["composition"]["background"])
        self.assertIn("no contact", result["causal_scope"])
        for section in (
            "video",
            "command_trace",
            "observed_trace",
            "review_frame",
        ):
            artifact = directory / result[section]["path"]
            self.assertTrue(artifact.is_file())
            self.assertEqual(
                hashlib.sha256(artifact.read_bytes()).hexdigest(),
                result[section]["sha256"],
            )

    def test_vendored_overlay_files_match_pinned_upstream_hashes(self):
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
