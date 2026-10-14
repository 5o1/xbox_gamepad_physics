"""Phase-1 rules run locally without SAPIEN or upstream assets."""

import json
import math
import copy
import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from teleop.session import (Command, GHOST_GROUP, NORMAL_GROUP, State,
                           StateMachine, assert_group_available, collision_allowed,
                           command_target)
from experiments.runner import load_config


class StateMachineTest(unittest.TestCase):
    def test_minimum_and_geometry_are_both_required(self):
        machine = StateMachine()
        machine.advance(True, 1., True)
        self.assertTrue(machine.ghost)
        machine.advance(False, 1.499, True)
        self.assertTrue(machine.ghost)
        machine.advance(False, 1.5, False)
        self.assertTrue(machine.ghost)
        self.assertTrue(machine.blocked)
        machine.advance(False, 8., False)
        self.assertTrue(machine.ghost)
        machine.advance(False, 8.004, True)
        self.assertEqual(machine.state, State.SECONDARY_NORMAL)
        self.assertFalse(machine.blocked)
        machine.advance(True, 9., False)
        self.assertEqual(machine.state, State.MAIN)

    def test_toggle_cancels_ghost_and_restarts_clock(self):
        machine = StateMachine()
        machine.advance(True, 0., False)
        machine.advance(True, .1, False)
        self.assertEqual(machine.state, State.MAIN)
        machine.advance(True, 2., True)
        machine.advance(False, 2.1, True)
        self.assertTrue(machine.ghost)

    def test_invalid_minimum(self):
        for value in (.49, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                StateMachine(value)


class FilterTest(unittest.TestCase):
    def test_all_gripper_pairs_filtered_external_allowed(self):
        gamepad = (1, 1, 0x80000000, 0x5842)
        table = (1, 1, 0, 0)
        for a in (NORMAL_GROUP, GHOST_GROUP):
            for b in (NORMAL_GROUP, GHOST_GROUP):
                self.assertFalse(collision_allowed(a, b))
        for external in (gamepad, table, (1, 0, 0, 0), (0, 1, 0, 0)):
            self.assertTrue(collision_allowed(NORMAL_GROUP, external))
            self.assertFalse(collision_allowed(GHOST_GROUP, external))
            self.assertFalse(collision_allowed(external, GHOST_GROUP))

    def test_scene_bits_and_reservation(self):
        self.assertFalse(collision_allowed(NORMAL_GROUP, (1, 1, 0, 0x10000)))
        assert_group_available([("gamepad", (1, 1, 0x80000000, 0x5842))])
        for group in ((1, 1, 0x40000000, 123), (1, 1, 0, 0x4752)):
            with self.assertRaisesRegex(ValueError, "occupied"):
                assert_group_available([("unrelated", group)])


class CommandConfigTest(unittest.TestCase):
    def test_config_and_registry(self):
        from experiments import EXPERIMENTS
        cfg = load_config(ROOT / "configs/teleop_gripper.yaml")
        self.assertIn(cfg["experiment"], EXPERIMENTS)
        self.assertEqual(cfg["gamepad"]["collision"], "sdf")
        self.assertFalse(cfg["scene"]["render"])
        self.assertIn("Test values", cfg["teleop"]["parameter_status"])
        for key in ("force_limit_n", "torque_limit_nm"):
            self.assertTrue(0 < cfg["teleop"]["root_drive"][key] < math.inf)
        self.assertTrue(0 < cfg["teleop"]["finger_drive"]["force_limit_n"] < math.inf)

    def test_world_ticks_and_actual_finger_bounds(self):
        cfg = load_config(ROOT / "configs/teleop_gripper.yaml")["teleop"]["input"]
        command = Command((1, -1, 0), (0, 0, 1), 1, fine=True)
        pose, finger = command_target([0, 0, 0, 1, 0, 0, 0], .02, command, cfg)
        self.assertEqual(pose[:3], [.001, -.001, 0])
        self.assertAlmostEqual(pose[3], math.cos(math.radians(.5)))
        self.assertAlmostEqual(finger, .021)
        _, finger = command_target(pose, finger, Command(opening=100), cfg)
        self.assertEqual(finger, .04765)
        _, finger = command_target(pose, finger, Command(opening=-100), cfg)
        self.assertEqual(finger, -.002)

    def test_command_roundtrip_and_nonfinite(self):
        from dataclasses import asdict
        data = json.loads(json.dumps(asdict(Command(toggle=True))))
        self.assertTrue(Command(**data).toggle)
        with self.assertRaises(ValueError):
            Command(translation=(float("nan"), 0, 0))


class RecordingReplayTest(unittest.TestCase):
    def test_v3_and_contiguous_steps(self):
        from experiments.teleop_replay import read_record
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"record.jsonl"
            header = {"type": "header", "schema_version": 3}
            path.write_text(json.dumps(header)+"\n"+json.dumps({"type": "step", "step": 0})+"\n")
            self.assertEqual(read_record(path)[0]["schema_version"], 3)
            path.write_text(json.dumps(header)+"\n"+json.dumps({"type": "step", "step": 1})+"\n")
            with self.assertRaisesRegex(ValueError, "non-contiguous"):
                read_record(path)

    def test_frozen_actual_joints_and_signals_are_checked(self):
        from experiments.teleop_replay import step_difference
        body = {"pose": [0,0,0,1,0,0,0], "joints": {"finger": .01}, "links": {}}
        expected = {role: copy.deepcopy(body) for role in ("main", "secondary", "frozen", "gamepad")}
        expected.update({"fixtures": {}, "signals": {"south": 0}, "state": "main",
                         "ghost": False, "ghost_blocked": False, "geometry_blockers": [], "contacts": [], "step": 0})
        actual = copy.deepcopy(expected)
        self.assertTrue(step_difference(expected, actual)["passed"])
        actual["frozen"]["joints"]["finger"] += 2e-9
        self.assertFalse(step_difference(expected, actual)["passed"])
        actual = copy.deepcopy(expected)
        actual["signals"]["south"] = 1e-12
        self.assertFalse(step_difference(expected, actual)["signals_equal"])


if __name__ == "__main__":
    unittest.main()
