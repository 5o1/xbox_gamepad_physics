import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "results" / "full_controls_user_review"


class FullControlsReviewMaterialsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((REVIEW / "manifest.json").read_text())

    def test_materials_are_pending_user_review(self):
        self.assertEqual(
            self.manifest["status"], "materials_ready_pending_user_review"
        )
        self.assertFalse(self.manifest["acceptance_decision_recorded"])
        self.assertEqual(len(self.manifest["groups"]), 6)

    def test_every_indexed_video_and_trace_exists(self):
        records = []
        for group in self.manifest["groups"].values():
            records.append(group["comparison_video"])
            for backend in ("robotwin", "mujoco"):
                records.extend(
                    (group[backend]["video"], group[backend]["trace"])
                )
        contact = self.manifest["physical_contact"]
        records.append(contact["comparison_video"])
        for backend in ("robotwin", "mujoco"):
            records.extend((contact[backend]["video"], contact[backend]["trace"]))

        self.assertEqual(len(records), 35)
        for record in records:
            with self.subTest(path=record["path"]):
                path = ROOT / record["path"]
                self.assertTrue(path.is_file())

    def test_contact_overlay_is_driven_by_physics_readback(self):
        robotwin = self.manifest["physical_contact"]["robotwin"]["trace"]
        mujoco = self.manifest["physical_contact"]["mujoco"]["trace"]
        self.assertEqual(
            robotwin["signal_source"],
            "sapien_articulation_qpos_readback_after_physics_steps",
        )
        self.assertEqual(
            mujoco["signal_source"],
            "mujoco_qpos_readback_after_mj_step",
        )
        self.assertGreater(robotwin["peak_abs_left_x"], 0.7)
        self.assertGreater(mujoco["peak_abs_left_x"], 0.7)
        self.assertLess(abs(robotwin["final_left_x"]), 1e-6)
        self.assertLess(abs(mujoco["final_left_x"]), 1e-6)


if __name__ == "__main__":
    unittest.main()
