from dataclasses import FrozenInstanceError
import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xbox_gamepad_physics.errors import (  # noqa: E402
    PhysicsNotReadyError,
    ResourceNotFoundError,
    StateValidationError,
    UnsafeResourcePathError,
)
from xbox_gamepad_physics.profiles import (  # noqa: E402
    load_profile,
    require_physics_ready,
)
from xbox_gamepad_physics.resources import (  # noqa: E402
    load_json_resource,
    resource_path,
)
from xbox_gamepad_physics.state import (  # noqa: E402
    AXIS_NAMES,
    BUTTON_NAMES,
    CHANNEL_COUNT,
    CHANNEL_NAMES,
    GAMEPAD_LAYOUT,
    GamepadState,
)


class GamepadStateTests(unittest.TestCase):
    def test_layout_matches_w3c_axes_then_buttons_contract(self):
        self.assertEqual(AXIS_NAMES, ("lx", "ly", "rx", "ry"))
        self.assertEqual(
            BUTTON_NAMES,
            (
                "a",
                "b",
                "x",
                "y",
                "left_shoulder",
                "right_shoulder",
                "left_trigger",
                "right_trigger",
                "view",
                "menu",
                "left_stick_click",
                "right_stick_click",
                "dpad_up",
                "dpad_down",
                "dpad_left",
                "dpad_right",
                "guide",
            ),
        )
        self.assertEqual(CHANNEL_COUNT, 21)
        self.assertEqual(tuple(item.name for item in GAMEPAD_LAYOUT), CHANNEL_NAMES)
        self.assertEqual(
            tuple(item.tensor_index for item in GAMEPAD_LAYOUT), tuple(range(21))
        )
        self.assertEqual(
            tuple(item.standard_index for item in GAMEPAD_LAYOUT[:4]), tuple(range(4))
        )
        self.assertEqual(
            tuple(item.standard_index for item in GAMEPAD_LAYOUT[4:]), tuple(range(17))
        )

    def test_state_is_immutable_and_dependency_free(self):
        state = GamepadState(lx=-0.5, right_trigger=0.75, a=1)
        self.assertEqual(len(state), 21)
        self.assertEqual(state.axes, (-0.5, 0.0, 0.0, 0.0))
        self.assertEqual(state.buttons[0], 1.0)
        self.assertEqual(state.buttons[7], 0.75)
        self.assertIsInstance(state.as_tuple(), tuple)
        with self.assertRaises(FrozenInstanceError):
            state.lx = 0.5

    def test_sequence_and_mapping_round_trip(self):
        values = (-1.0, -0.5, 0.5, 1.0) + tuple(
            index / 16 for index in range(17)
        )
        state = GamepadState.from_sequence(values)
        self.assertEqual(state.as_tuple(), values)
        self.assertEqual(GamepadState.from_mapping(state.as_dict()), state)

    def test_bad_shape_range_and_non_finite_values_are_rejected(self):
        with self.assertRaises(StateValidationError):
            GamepadState.from_sequence([0.0] * 20)
        with self.assertRaises(StateValidationError):
            GamepadState(lx=1.01)
        with self.assertRaises(StateValidationError):
            GamepadState(a=-0.01)
        with self.assertRaises(StateValidationError):
            GamepadState(rx=math.nan)
        with self.assertRaises(StateValidationError):
            GamepadState(a=True)


class ResourceAndProfileTests(unittest.TestCase):
    def test_packaged_manifests_are_explicitly_blocked(self):
        for backend in ("robotwin", "mujoco"):
            manifest = load_json_resource(backend, "estimated_v0")
            self.assertEqual(manifest["asset_id"], "xbox_one_s")
            self.assertEqual(manifest["backend"], backend)
            self.assertIs(manifest["available"], False)
            self.assertIs(manifest["dynamics_ready"], False)
            self.assertIsNone(manifest["entrypoint"])
            self.assertTrue(manifest["required_files"])
            self.assertTrue(manifest["reason"])

            profile = load_profile(backend, "estimated_v0")
            self.assertFalse(profile.physics_ready)
            self.assertIsInstance(profile.required_files, tuple)
            with self.assertRaises(PhysicsNotReadyError):
                require_physics_ready(backend, "estimated_v0")

    def test_default_resource_is_manifest(self):
        path = resource_path("mujoco", "estimated_v0")
        self.assertEqual(path.name, "manifest.json")
        self.assertTrue(path.is_file())

    def test_missing_resource_fails_closed(self):
        with self.assertRaises(ResourceNotFoundError):
            resource_path("mujoco", "estimated_v0", "xbox_one_s.xml")
        with self.assertRaises(ResourceNotFoundError):
            load_json_resource("mujoco", "does_not_exist")

    def test_path_traversal_is_rejected(self):
        unsafe_requests = (
            ("../mujoco", "estimated_v0", ()),
            ("mujoco", "../estimated_v0", ()),
            ("mujoco", "estimated_v0", ("../manifest.json",)),
            ("mujoco", "estimated_v0", ("/etc/passwd",)),
            ("mujoco", "estimated_v0", ("visual\\..\\manifest.json",)),
        )
        for backend, profile, parts in unsafe_requests:
            with self.subTest(backend=backend, profile=profile, parts=parts):
                with self.assertRaises(UnsafeResourcePathError):
                    resource_path(backend, profile, *parts, must_exist=False)


if __name__ == "__main__":
    unittest.main()
