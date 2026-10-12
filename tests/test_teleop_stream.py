"""Input safety, AU framing and latest-state boundaries without SAPIEN."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from teleop.inputs import Inputs
from teleop.stream.h264 import AccessUnits, info
from teleop.stream.ipc import Latest, packet, unpack


class InputsTest(unittest.TestCase):
    def test_stop_clears_held_and_pending_then_requires_focus(self):
        state=Inputs()
        state.accept({'seq':1,'kind':'focus'},0)
        state.accept({'seq':2,'kind':'keys','keys':['KeyW']},1)
        self.assertEqual(state.command(.004).translation,(1,0,0))
        state.accept({'seq':3,'kind':'delta','rotation':[0,0,1]},2)
        state.accept({'seq':4,'kind':'stop'},2)
        self.assertFalse(state.command(.008).stop)
        self.assertTrue(state.hold)
        self.assertEqual(state.cancelled,[3])
        state.accept({'seq':5,'kind':'keys','keys':['KeyW']},3)
        self.assertEqual(state.command(.012).translation,(0,0,0))
        self.assertFalse(state.pending)
        self.assertFalse(state.accept({'seq':3,'kind':'focus'},4))

    def test_repeat_is_simulation_time_and_disconnect_stops(self):
        state=Inputs(.05)
        state.accept({'seq':1,'kind':'focus'},0)
        state.accept({'seq':2,'kind':'keys','keys':['KeyE','ShiftLeft']},1)
        self.assertTrue(state.command(0).fine)
        self.assertEqual(state.command(.004).translation,(0,0,0))
        self.assertEqual(state.command(.05).translation,(0,0,-1))
        state.accept({'seq':3,'kind':'disconnect'},20)
        self.assertFalse(state.command(.08).stop)
        self.assertTrue(state.hold)


    def test_queued_mouse_deltas_ack_only_after_their_physics_step(self):
        state=Inputs()
        for message in ({'seq':1,'kind':'focus'},
                        {'seq':2,'kind':'delta','rotation':[0,0,1]},
                        {'seq':3,'kind':'delta','rotation':[0,0,2]},
                        {'seq':4,'kind':'keys','keys':['KeyW']}):
            state.accept(message,0)
        self.assertEqual(state.seq,4)
        self.assertEqual(state.command(0).rotation,(0,0,1))
        self.assertEqual(state.applied_seq,0) # even prepared command not acknowledged yet
        self.assertEqual(state.commit(),2)
        self.assertEqual(state.command(.004).rotation,(0,0,2))
        self.assertEqual(state.applied_seq,2)
        self.assertEqual(state.commit(),3)
        self.assertEqual(state.command(.008).translation,(1,0,0))
        self.assertEqual(state.commit(),4)

    def test_lease_clears_motion_at_first_boundary_without_rebasing_target(self):
        state=Inputs(lease_seconds=.2)
        state.accept({'seq':1,'kind':'focus','received_ns':1000000000},0)
        state.accept({'seq':2,'kind':'keys','keys':['KeyW'],'received_ns':1000000000},0)
        state.command(0,1000000000);state.commit()
        self.assertEqual(state.command(.2,1200000000).translation,(0,0,0))
        self.assertTrue(state.hold)
        self.assertEqual(state.hold_reason,'lease-expired')
        self.assertFalse(state.command(.204,1204000000).stop)
        self.assertFalse(state.armed)

class IPCCodecTest(unittest.TestCase):
    def test_latest_packet_and_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'latest'
            writer=Latest(path,300,True); reader=Latest(path,300)
            self.assertIsNone(reader.read())
            writer.write(packet({'step':20},b'pixel'))
            self.assertEqual(unpack(reader.read()[1]),({'step':20},b'pixel'))
            writer.write(packet({'step':21},b'new'))
            self.assertEqual(unpack(reader.read()[1])[0]['step'],21)
            with self.assertRaises(ValueError):writer.write(b'x'*301)
            writer.close();reader.close()

    def test_aud_units_survive_every_byte_boundary(self):
        a=b'\0\0\0\1\x09\x10\0\0\1\x67\x4d\x40\x2a\0\0\1\x65abc'
        b=b'\0\0\1\x09\x10\0\0\1\x41def'
        for split in range(1,len(a+b)):
            parser=AccessUnits()
            units=parser.feed((a+b)[:split])+parser.feed((a+b)[split:])
            self.assertEqual(units,[a])
            self.assertEqual(info(units[0]),(True,'avc1.4D402A'))


if __name__=='__main__':unittest.main()
