"""Score contact closure from the controller record, leaving motion unchanged."""
import json,unittest
from pathlib import Path
from unittest.mock import patch
from teleop.ball_acceptance import acceptance_threshold,evaluate,scoring_misfires
from teleop.ball_probe import threshold,case_spec

class DpadRescoreTest(unittest.TestCase):
    def test_scoring_reads_record_but_pressure_stop_is_unchanged(self):
        expected=json.loads((Path(__file__).resolve().parents[1]/'references/full_controls.json').read_text())['signal_policy']['dpad_contact_closure']['threshold']
        self.assertEqual(acceptance_threshold('dpad_down'),expected)
        self.assertEqual(threshold('dpad_down'),.95)
        with patch('teleop.ball_acceptance.Path.read_text',return_value=json.dumps({'signal_policy':{'dpad_contact_closure':{'threshold':.4}}})):
            self.assertEqual(acceptance_threshold('dpad_up'),.4)
        self.assertEqual(acceptance_threshold('guide'),.95)
        self.assertEqual(acceptance_threshold('left_x'),.9)
    def test_other_dpad_contact_is_a_misfire_at_the_same_record_threshold(self):
        values={'dpad_down':.5,'dpad_left':.35,'south':.5}
        self.assertEqual(scoring_misfires(case_spec('Dpad_down'),values),{'dpad_left':.35})

    def test_original_record_is_scored_without_replaying_physics(self):
        signals=dict.fromkeys(('dpad_up','dpad_down','dpad_left','dpad_right'),0)
        signals['dpad_down']=.45
        def row(step,phase):
            neutral=phase in ('withdraw','observe')
            return {'step':step,'probe':{'phase':phase,'events':{},'force_n':[0,0,-1]},
                'signals':dict.fromkeys(signals,0) if neutral else dict(signals),
                'gamepad_internal_pairs':0,'contacts':[]}
        rows=[row(i,'hold') for i in range(125)]+[row(125,'withdraw'),row(126,'observe'),row(127,'observe')]
        browser={'overlay_applied':{'meta':{'signals':signals,'probe':{'events':{}}}},'overlay_passed':True,
                 'unexpected_components':[],'overlay_color':{},'all_inputs_canonical_32_from_rendered_signals':True}
        result=evaluate('Dpad_down',rows,browser)
        self.assertTrue(result['passed']);self.assertFalse(result['dpad_bottomed_noncritical'])
