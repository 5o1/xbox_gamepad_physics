import json
import math
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from summarize_xbox_artist_animation import summarize


class ArtistAnimationSummaryTest(unittest.TestCase):
    def test_records_peaks_and_neutral_residual_without_physical_promotion(self):
        angle = 0.25
        cosine, sine = math.cos(angle), math.sin(angle)
        # Rotation about X through p=(0, 2, 3): t=(I-R)p.
        rotation = [[1, 0, 0], [0, cosine, -sine], [0, sine, cosine]]
        pivot = [0, 2, 3]
        translation = [
            pivot[row] - sum(rotation[row][column] * pivot[column] for column in range(3))
            for row in range(3)
        ]
        samples = [
            {
                "frame": 0,
                "translation_native": [0, 0, 0],
                "rotation_angle_rad": 0,
                "rotation_axis_world": [0, 0, 0],
                "relative_matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            },
            {
                "frame": 1,
                "translation_native": translation,
                "rotation_angle_rad": angle,
                "rotation_axis_world": [1, 0, 0],
                "relative_matrix": [
                    rotation[0] + [translation[0]],
                    rotation[1] + [translation[1]],
                    rotation[2] + [translation[2]],
                    [0, 0, 0, 1],
                ],
            },
            {
                "frame": 2,
                "translation_native": [0, 0, 0],
                "rotation_angle_rad": 0,
                "rotation_axis_world": [0, 0, 0],
                "relative_matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            },
        ]
        report = {
            "status": "artist_animation_audit_not_physical_calibration",
            "source": "candidate.glb",
            "source_sha256": "a" * 64,
            "coordinate_unit": "source_native_unit",
            "time_unit": "artist_frame_not_seconds",
            "toolchain": {
                "blender_version": [4, 5, 9],
                "blender_version_string": "4.5.9 LTS",
                "blender_build_hash": "test",
                "python_version": "test",
            },
            "actions": [
                {
                    "name": "Test",
                    "frame_range": [0, 2],
                    "keyframes": [0, 1, 2],
                    "animated_bones": [
                        {
                            "bone": "A",
                            "baseline_frame": 0,
                            "baseline_pose_matrix": [
                                [1, 0, 0, pivot[0]],
                                [0, 1, 0, pivot[1]],
                                [0, 0, 1, pivot[2]],
                                [0, 0, 0, 1],
                            ],
                            "rest_head_world_native": [0, 0, 0],
                            "rest_tail_world_native": [0, 0, 1],
                            "samples": samples,
                        }
                    ],
                }
            ],
        }
        summary = summarize(json.dumps(report).encode())
        bone = summary["actions"][0]["bones"][0]
        self.assertAlmostEqual(bone["peak_translation"]["magnitude_native"], math.sqrt(sum(value * value for value in translation)))
        self.assertAlmostEqual(bone["peak_rotation"]["angle_rad"], 0.25)
        fit = bone["effective_rotation_pivot_fit"]
        self.assertEqual(fit["solution_kind"], "single_axis_minimum_norm_line_point")
        self.assertAlmostEqual(fit["effective_pivot_world_native"][1], 2)
        self.assertAlmostEqual(fit["effective_pivot_world_native"][2], 3)
        self.assertAlmostEqual(fit["translation_fit_max_native"], 0)
        self.assertEqual(bone["baseline_pose_origin_world_native"], pivot)
        self.assertAlmostEqual(fit["baseline_origin_translation_fit_max_native"], 0)
        self.assertEqual(bone["end_frame_residual"]["translation_native"], 0)
        self.assertIn("not_physical_calibration", summary["status"])
        self.assertEqual(summary["toolchain"]["blender_version"], [4, 5, 9])

    def test_rejects_unlabelled_input(self):
        with self.assertRaisesRegex(ValueError, "not an artist-animation audit"):
            summarize(json.dumps({"status": "physics"}).encode())


if __name__ == "__main__":
    unittest.main()
