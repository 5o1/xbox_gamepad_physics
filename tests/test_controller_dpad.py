"""D-pad contact closure preserves amplitudes and genuine diagonals."""
import json,unittest
from pathlib import Path
from unittest.mock import patch
from xbox_gamepad_physics.controller import (GamepadSignalController,SplitSignalMapping,
    RadialSourceGroup,AxisSignalMapping,ScalarSignalMapping)
from xbox_gamepad_physics.state import GamepadState

CHANNELS=('dpad_up','dpad_down','dpad_left','dpad_right')

class DpadContactTest(unittest.TestCase):
    def setUp(self):
        self.controller=self.make()
        record=json.loads((Path(__file__).resolve().parents[1]/'references/full_controls.json').read_text())
        self.threshold=record['signal_policy']['dpad_contact_closure']['threshold']
    def make(self):
        return GamepadSignalController.xbox_one_s(
            (AxisSignalMapping('left_x','stick_x',-1,1),AxisSignalMapping('left_y','stick_y',-1,1)),
            scalar_mappings=(ScalarSignalMapping('south','button',0,1),ScalarSignalMapping('left_trigger','trigger',0,1)),
            split_mappings=(SplitSignalMapping('dpad_left','dpad_right','dx',-1,1),
                            SplitSignalMapping('dpad_up','dpad_down','dy',-1,1)),
            radial_source_groups=(RadialSourceGroup(('dx','dy'),1,1e-4),))
    def encode(self,x,y,controller=None):
        return (controller or self.controller).encode(dict(dx=x,dy=y,stick_x=.3,stick_y=-.2,button=.7,trigger=.6))
    def test_full_single_direction(self):
        s=self.encode(1,0);self.assertEqual(s.channel('dpad_right'),1)
        self.assertTrue(all(s.channel(n)==0 for n in CHANNELS if n!='dpad_right'))
    def test_small_orthogonal_values_are_cleared(self):
        for tiny in (.005,4.6e-5):
            s=self.encode(-tiny,-.96)
            self.assertEqual(s.channel('dpad_left'),0);self.assertEqual(s.channel('dpad_up'),.96)
    def test_just_below_and_exact_threshold(self):
        self.assertEqual(self.encode(self.threshold-1e-9,0).channel('dpad_right'),0)
        self.assertEqual(self.encode(self.threshold,0).channel('dpad_right'),self.threshold)
    def test_real_diagonal_outputs_both_amplitudes(self):
        s=self.encode(.8,-.6)
        self.assertEqual(s.channel('dpad_right'),.8);self.assertEqual(s.channel('dpad_up'),.6)
        s=self.encode(-1,-1)
        self.assertAlmostEqual(s.channel('dpad_up'),2**-.5)
        self.assertAlmostEqual(s.channel('dpad_left'),2**-.5)
    def test_zero_other_channels_and_decode(self):
        s=self.encode(0,0);self.assertTrue(all(s.channel(n)==0 for n in CHANNELS))
        for n,v in {'left_x':.3,'left_y':-.2,'south':.7,'left_trigger':.6}.items():self.assertEqual(s.channel(n),v)
        targets=self.controller.decode_joint_targets(GamepadState.xbox_one_s({'dpad_left':.1,'dpad_up':.6}))
        self.assertEqual(targets['dx'],-.1);self.assertEqual(targets['dy'],-.6)
    def test_threshold_is_loaded_from_record_not_literal(self):
        payload={'signal_policy':{'dpad_contact_closure':{'threshold':.6}}}
        with patch('xbox_gamepad_physics.controller.Path.read_text',return_value=json.dumps(payload)):
            c=self.make()
        self.assertEqual(self.encode(.5,0,c).channel('dpad_right'),0)
        self.assertEqual(self.encode(.6,0,c).channel('dpad_right'),.6)
