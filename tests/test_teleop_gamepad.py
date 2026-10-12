"""Gamepad toggle remains an edge command and follows existing stop ordering."""
import unittest
from dataclasses import asdict
from teleop.inputs import Inputs
from teleop.session import Command


class GamepadCommandTest(unittest.TestCase):
    def test_edge_and_record_roundtrip(self):
        controls=Inputs()
        controls.accept({'kind':'focus','seq':1},0)
        controls.accept({'kind':'delta','seq':2,'toggle_gamepad':True},0)
        command=controls.command(0)
        self.assertTrue(command.toggle_gamepad)
        self.assertEqual(Command(**asdict(command)),command)
        controls.commit()
        self.assertFalse(controls.command(.004).toggle_gamepad)

    def test_stop_cancels_queued_toggle(self):
        controls=Inputs()
        for message in ({'kind':'focus','seq':1},{'kind':'delta','seq':2,'toggle_gamepad':True},{'kind':'stop','seq':3}):
            controls.accept(message,0)
        self.assertFalse(controls.command(0).toggle_gamepad)
        self.assertFalse(controls.armed)
