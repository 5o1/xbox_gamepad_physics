import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import mujoco  # noqa: F401
except ImportError:
    mujoco = None

from xbox_gamepad_physics.muble import (
    MUBLE_BODY_POSE_TRACE_SCHEMA,
    PoseCommand,
    derive_part_to_body,
    export_pose_trace,
    visual_records,
)
from xbox_gamepad_physics.state import GamepadState


class MuBlEVisualMetadataTest(unittest.TestCase):
    def test_packaged_manifest_reuses_sixteen_blender_objects(self):
        records = visual_records()
        self.assertEqual(len(records), 16)
        self.assertEqual(len({item["source_object"] for item in records.values()}), 16)
        self.assertTrue(all(len(item["source_matrix_world"]) == 4 for item in records.values()))


class MuBlEPoseExportUnitTest(unittest.TestCase):
    def test_trace_export_does_not_require_robotwin_metadata(self):
        parts = tuple(visual_records())
        body_names = ("a", "b", *(f"body_{index}" for index in range(2, 16)))

        class Model:
            def geom(self, name):
                return SimpleNamespace(bodyid=parts.index(name.removeprefix("visual_")))

            def body(self, index):
                return SimpleNamespace(name=body_names[int(index)])

        class Data:
            def __init__(self):
                self.time = 0.0
                self.positions = {name: [0.0, 0.0, 0.0] for name in body_names}

            def body(self, name):
                return SimpleNamespace(
                    xpos=self.positions[name],
                    xquat=[1.0, 0.0, 0.0, 0.0],
                )

        data = Data()

        class Handle:
            def set_gamepad_state(self, state):
                data.positions["a"] = [0.0, 0.0, state.channel("south")]

            def physical_events(self):
                return {"pair_bind_connect": 0.0}

            def set_physical_events(self, events):
                self.events = dict(events)

        loaded = SimpleNamespace(
            model=Model(), data=data, gamepad=Handle(), profile="full_controls"
        )
        fake_mujoco = SimpleNamespace(
            mj_forward=lambda model, runtime_data: None,
            mj_step=lambda model, runtime_data: setattr(
                runtime_data, "time", runtime_data.time + 0.00416666666667
            ),
        )
        with patch.dict("sys.modules", {"mujoco": fake_mujoco}):
            trace = export_pose_trace(
                loaded,
                (
                    PoseCommand("neutral", GamepadState.xbox_one_s({})),
                    PoseCommand(
                        "a_pressed", GamepadState.xbox_one_s({"south": 1.0})
                    ),
                ),
            )
        self.assertEqual(trace["schema"], MUBLE_BODY_POSE_TRACE_SCHEMA)
        self.assertEqual(trace["part_to_body"][parts[0]], "a")
        self.assertNotEqual(
            trace["frames"][0]["bodies"]["a"],
            trace["frames"][1]["bodies"]["a"],
        )
        self.assertEqual(
            trace["frames"][0]["bodies"]["b"],
            trace["frames"][1]["bodies"]["b"],
        )


@unittest.skip("Historical resource tree is retained for provenance only.")
class MuBlEPoseExportTest(unittest.TestCase):
    def test_public_mujoco_handle_exports_muble_trace(self):
        from xbox_gamepad_physics.mujoco import load_scene

        loaded = load_scene(profile="full_controls", scene="fixed")
        part_to_body = derive_part_to_body(loaded.model)
        self.assertEqual(len(part_to_body), 16)

        neutral = GamepadState.xbox_one_s({})
        a_pressed = GamepadState.xbox_one_s({"south": 1.0})
        trace = export_pose_trace(
            loaded,
            (
                PoseCommand("neutral", neutral),
                PoseCommand("a_pressed", a_pressed),
            ),
        )
        self.assertEqual(trace["schema"], MUBLE_BODY_POSE_TRACE_SCHEMA)
        self.assertEqual(trace["part_to_body"], part_to_body)
        self.assertEqual([item["frame_index"] for item in trace["frames"]], [0, 1])
        self.assertNotEqual(
            trace["frames"][0]["bodies"]["a"],
            trace["frames"][1]["bodies"]["a"],
        )
        self.assertEqual(
            trace["frames"][0]["bodies"]["b"],
            trace["frames"][1]["bodies"]["b"],
        )


if __name__ == "__main__":
    unittest.main()
