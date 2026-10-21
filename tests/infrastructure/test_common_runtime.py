from dataclasses import FrozenInstanceError
import math
from pathlib import Path
import sys
import unittest

try:
    import torch
except ImportError:
    torch = None


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xbox_gamepad_physics.errors import (  # noqa: E402
    ResourceNotFoundError,
    StateValidationError,
    UnsafeResourcePathError,
)
from xbox_gamepad_physics.controller import (  # noqa: E402
    AxisSignalMapping,
    GamepadSignalController,
    RadialSourceGroup,
    RadialSignalGroup,
    ScalarSignalMapping,
    SplitSignalMapping,
)
from xbox_gamepad_physics.profiles import load_profile  # noqa: E402
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
    TENSOR_LAYOUT_ID,
    W3C_STANDARD_TO_CANONICAL,
    XBOX_ONE_S_CHANNELS,
    GamepadDeviceId,
    GamepadState,
)


class GamepadStateTests(unittest.TestCase):
    def test_layout_matches_versioned_sdl3_axes_then_buttons_contract(self):
        self.assertEqual(TENSOR_LAYOUT_ID, "sdl3-gamepad-core-v1")
        self.assertEqual(
            AXIS_NAMES,
            (
                "left_x",
                "left_y",
                "right_x",
                "right_y",
                "left_trigger",
                "right_trigger",
            ),
        )
        self.assertEqual(
            BUTTON_NAMES,
            (
                "south",
                "east",
                "west",
                "north",
                "back",
                "guide",
                "start",
                "left_stick",
                "right_stick",
                "left_shoulder",
                "right_shoulder",
                "dpad_up",
                "dpad_down",
                "dpad_left",
                "dpad_right",
                "misc1",
                "right_paddle1",
                "left_paddle1",
                "right_paddle2",
                "left_paddle2",
                "touchpad",
                "misc2",
                "misc3",
                "misc4",
                "misc5",
                "misc6",
            ),
        )
        self.assertEqual(CHANNEL_COUNT, 32)
        self.assertEqual(tuple(item.name for item in GAMEPAD_LAYOUT), CHANNEL_NAMES)
        self.assertEqual(
            tuple(item.tensor_index for item in GAMEPAD_LAYOUT), tuple(range(32))
        )
        self.assertEqual(
            tuple(item.standard_index for item in GAMEPAD_LAYOUT[:6]), tuple(range(6))
        )
        self.assertEqual(
            tuple(item.standard_index for item in GAMEPAD_LAYOUT[6:]), tuple(range(26))
        )

    def test_xbox_state_is_fixed_width_immutable_and_dependency_free(self):
        state = GamepadState.xbox_one_s(
            {"left_x": -0.5, "right_trigger": 0.75, "south": 1.0}
        )
        self.assertEqual(len(state), 32)
        self.assertEqual(state.device_id, GamepadDeviceId.XBOX_ONE_S)
        self.assertEqual(state.channel("left_x"), -0.5)
        self.assertEqual(state.channel("right_trigger"), 0.75)
        self.assertEqual(state.channel("south"), 1.0)
        self.assertEqual(sum(state.available_mask), 21)
        self.assertEqual(sum(state.task_mask), 21)
        self.assertEqual(sum(state.action_mask), 21)
        self.assertIsInstance(state.values, tuple)
        with self.assertRaises(FrozenInstanceError):
            state.values = (0.0,) * 32

    def test_zero_value_and_unavailable_channel_are_distinguished_by_mask(self):
        state = GamepadState.xbox_one_s()
        self.assertEqual(state.channel("left_x"), 0.0)
        self.assertTrue(state.is_available("left_x"))
        self.assertEqual(state.channel("right_paddle1"), 0.0)
        self.assertFalse(state.is_available("right_paddle1"))

    def test_task_mask_is_a_subset_and_controls_action_mask(self):
        state = GamepadState.xbox_one_s(
            {"left_x": 0.25, "left_y": -0.5, "south": 1.0},
            task_channels=("left_x", "left_y"),
        )
        self.assertTrue(state.is_task_channel("left_x"))
        self.assertFalse(state.is_task_channel("south"))
        self.assertEqual(sum(state.action_mask), 2)
        self.assertEqual(state.masked_action_values[0:2], (0.25, -0.5))
        self.assertEqual(state.masked_action_values[6], 0.0)
        self.assertEqual(state.action_mask_values[0:2], (1.0, 1.0))

    def test_xbox_profile_contains_exactly_its_21_control_channels(self):
        state = GamepadState.xbox_one_s()
        available = tuple(
            name
            for name, enabled in zip(CHANNEL_NAMES, state.available_mask, strict=True)
            if enabled
        )
        self.assertEqual(available, XBOX_ONE_S_CHANNELS)

    def test_w3c_boundary_is_reordered_into_the_canonical_layout(self):
        browser_values = [0.0] * 21
        browser_values[0] = -0.25
        browser_values[6] = 1.0  # W3C X button -> positional west button.
        browser_values[10] = 0.75  # W3C left trigger button -> SDL trigger axis.
        browser_available = [True] * 20 + [False]
        state = GamepadState.from_w3c_standard(
            browser_values,
            browser_available,
            device_id=GamepadDeviceId.XBOX_ONE_S,
        )
        self.assertEqual(len(W3C_STANDARD_TO_CANONICAL), 21)
        self.assertEqual(state.channel("left_x"), -0.25)
        self.assertEqual(state.channel("west"), 1.0)
        self.assertEqual(state.channel("left_trigger"), 0.75)
        self.assertFalse(state.is_available("guide"))
        self.assertEqual(state.channel("guide"), 0.0)

    @unittest.skipIf(torch is None, "Torch is an optional training dependency")
    def test_numeric_action_mask_preserves_gradients_on_active_channels(self):
        state = GamepadState.xbox_one_s(
            task_channels=("left_x", "left_y", "south")
        )
        prediction = torch.ones(2, CHANNEL_COUNT, requires_grad=True)
        mask = prediction.new_tensor(state.action_mask_values)
        loss = (prediction.square() * mask).sum()
        loss.backward()

        expected = torch.zeros_like(prediction)
        expected[:, 0] = 2.0
        expected[:, 1] = 2.0
        expected[:, 6] = 2.0
        torch.testing.assert_close(prediction.grad, expected)

    def test_bad_shape_range_and_non_finite_values_are_rejected(self):
        with self.assertRaises(StateValidationError):
            GamepadState(
                values=(0.0,) * 31,
                available_mask=(False,) * 32,
                task_mask=(False,) * 32,
                device_id=0,
            )
        with self.assertRaises(StateValidationError):
            GamepadState.xbox_one_s({"left_x": 1.01})
        with self.assertRaises(StateValidationError):
            GamepadState.xbox_one_s({"south": -0.01})
        with self.assertRaises(StateValidationError):
            GamepadState.xbox_one_s({"right_x": math.nan})
        with self.assertRaises(StateValidationError):
            GamepadState.xbox_one_s({"south": True})
        with self.assertRaises(StateValidationError):
            GamepadState.xbox_one_s(task_channels=("right_paddle1",))
        with self.assertRaises(StateValidationError):
            GamepadState.xbox_one_s(
                {"left_x": 0.0}, available_channels=("left_y",)
            )


class GamepadSignalControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = GamepadSignalController.xbox_one_s(
            (
                AxisSignalMapping("left_x", "stick_x", -0.4, 0.4),
                AxisSignalMapping("left_y", "stick_y", -0.4, 0.4),
            ),
            (RadialSignalGroup(("left_x", "left_y"), 1.0),),
        )

    def test_controller_normalizes_saturates_and_projects_radially(self):
        state = self.controller.encode({"stick_x": 0.4, "stick_y": 0.4})
        self.assertAlmostEqual(state.channel("left_x"), 2**-0.5)
        self.assertAlmostEqual(state.channel("left_y"), 2**-0.5)
        self.assertEqual(sum(state.available_mask), 2)

        saturated = self.controller.encode({"stick_x": -0.8, "stick_y": 0.0})
        self.assertEqual(saturated.channel("left_x"), -1.0)

    def test_neutral_epsilon_zeros_solver_residue_without_rescaling(self):
        controller = GamepadSignalController.xbox_one_s(
            (
                AxisSignalMapping("left_x", "stick_x", -0.4, 0.4),
                AxisSignalMapping("left_y", "stick_y", -0.4, 0.4),
            ),
            (RadialSignalGroup(("left_x", "left_y"), 1.0, 1e-4),),
            scalar_mappings=(
                ScalarSignalMapping(
                    "left_trigger", "trigger", 0.0, 0.3, 1e-4
                ),
            ),
            split_mappings=(
                SplitSignalMapping(
                    "dpad_left", "dpad_right", "dpad_x", -0.2, 0.2
                ),
                SplitSignalMapping(
                    "dpad_up", "dpad_down", "dpad_y", -0.2, 0.2
                ),
            ),
            radial_source_groups=(
                RadialSourceGroup(("dpad_x", "dpad_y"), 1.0, 1e-4),
            ),
        )
        neutral = controller.encode(
            {
                "stick_x": 0.4 * 5e-5,
                "stick_y": 0.0,
                "trigger": 0.3 * 5e-5,
                "dpad_x": 0.2 * 5e-5,
                "dpad_y": 0.0,
            }
        )
        self.assertEqual(neutral.channel("left_x"), 0.0)
        self.assertEqual(neutral.channel("left_trigger"), 0.0)
        self.assertEqual(neutral.channel("dpad_right"), 0.0)

        outside = controller.encode(
            {
                "stick_x": 0.4 * 2e-4,
                "stick_y": 0.0,
                "trigger": 0.3 * 2e-4,
                "dpad_x": 0.2 * 2e-4,
                "dpad_y": 0.0,
            }
        )
        self.assertAlmostEqual(outside.channel("left_x"), 2e-4)
        self.assertAlmostEqual(outside.channel("left_trigger"), 2e-4)
        self.assertEqual(outside.channel("dpad_right"), 0.0)

    def test_controller_rejects_invalid_configuration_and_observations(self):
        with self.assertRaisesRegex(StateValidationError, "missing mechanism"):
            self.controller.encode({"stick_x": 0.0})
        with self.assertRaisesRegex(StateValidationError, "must be finite"):
            self.controller.encode({"stick_x": math.nan, "stick_y": 0.0})
        with self.assertRaisesRegex(StateValidationError, "not a stick axis"):
            GamepadSignalController.xbox_one_s(
                (AxisSignalMapping("south", "button", -1.0, 1.0),)
            )

    def test_scalar_and_split_controls_share_the_canonical_state(self):
        controller = GamepadSignalController.xbox_one_s(
            (),
            scalar_mappings=(
                ScalarSignalMapping("south", "a_press", 0.0, 0.001),
                ScalarSignalMapping("left_trigger", "lt", 0.0, 0.3),
            ),
            split_mappings=(
                SplitSignalMapping(
                    "dpad_left", "dpad_right", "dpad_horizontal", -0.2, 0.2
                ),
                SplitSignalMapping(
                    "dpad_up", "dpad_down", "dpad_vertical", -0.2, 0.2
                ),
            ),
            radial_source_groups=(
                RadialSourceGroup(("dpad_horizontal", "dpad_vertical"), 1.0),
            ),
        )
        state = controller.encode(
            {
                "a_press": 0.00075,
                "lt": 0.15,
                "dpad_horizontal": -0.2,
                "dpad_vertical": -0.2,
            }
        )
        self.assertAlmostEqual(state.channel("south"), 0.75)
        self.assertAlmostEqual(state.channel("left_trigger"), 0.5)
        self.assertAlmostEqual(state.channel("dpad_left"), 2**-0.5)
        self.assertAlmostEqual(state.channel("dpad_up"), 2**-0.5)
        self.assertEqual(state.channel("dpad_right"), 0.0)
        self.assertEqual(state.channel("dpad_down"), 0.0)
        self.assertEqual(sum(state.available_mask), 6)

        targets = controller.decode_joint_targets(state)
        restored = controller.encode(targets)
        for channel in controller.available_channels:
            self.assertAlmostEqual(restored.channel(channel), state.channel(channel))

    def test_physical_event_mapping_is_bidirectional(self):
        from xbox_gamepad_physics.controller import PhysicalEventMapping

        controller = GamepadSignalController.xbox_one_s(
            (),
            physical_event_mappings=(
                PhysicalEventMapping("pair_bind_connect", "pair_press", 0.0, 0.001),
            ),
        )
        targets = controller.decode_physical_event_targets(
            {"pair_bind_connect": 0.4}
        )
        self.assertEqual(targets, {"pair_press": 0.0004})
        self.assertEqual(
            controller.encode_physical_events(targets),
            {"pair_bind_connect": 0.4},
        )


class ResourceAndProfileTests(unittest.TestCase):
    def test_packaged_full_control_manifests_are_ready(self):
        for backend in ("robotwin",):
            manifest = load_json_resource(backend, "full_controls")
            self.assertEqual(manifest["asset_id"], "xbox_one_s")
            self.assertEqual(manifest["backend"], backend)
            self.assertIsInstance(manifest["entrypoint"], str)
            self.assertTrue(manifest["required_files"])
            self.assertIsNone(manifest["reason"])

            profile = load_profile(backend, "full_controls")
            self.assertIsInstance(profile.required_files, tuple)

    def test_default_resource_is_manifest(self):
        path = resource_path("robotwin", "full_controls")
        self.assertEqual(path.name, "manifest.json")
        self.assertTrue(path.is_file())

    def test_missing_resource_fails_closed(self):
        with self.assertRaises(ResourceNotFoundError):
            resource_path("robotwin", "full_controls", "does_not_exist.urdf")
        with self.assertRaises(ResourceNotFoundError):
            load_json_resource("robotwin", "does_not_exist")

    def test_path_traversal_is_rejected(self):
        unsafe_requests = (
            ("../robotwin", "full_controls", ()),
            ("robotwin", "../full_controls", ()),
            ("robotwin", "full_controls", ("../manifest.json",)),
            ("robotwin", "full_controls", ("/etc/passwd",)),
            ("robotwin", "full_controls", ("visual\\..\\manifest.json",)),
        )
        for backend, profile, parts in unsafe_requests:
            with self.subTest(backend=backend, profile=profile, parts=parts):
                with self.assertRaises(UnsafeResourcePathError):
                    resource_path(backend, profile, *parts, must_exist=False)


if __name__ == "__main__":
    unittest.main()
