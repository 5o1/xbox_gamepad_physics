"""Yellow highlighting requires paint; moving a gray circle is insufficient."""
import unittest
from teleop.overlay_colors import color_verdict

class YellowVerdictTest(unittest.TestCase):
    def test_movement_without_yellow_fails(self):
        result=color_verdict({'left:analog-stick':[{'yellow':False,'rect':[9,4,20,20]}]}, {'left:analog-stick'})
        self.assertFalse(result['passed'])
    def test_target_yellow_and_extra_yellow_are_checked_separately(self):
        target={'right:down':[{'yellow':True}], 'left:up':[{'yellow':False}]}
        self.assertTrue(color_verdict(target,{'right:down'})['passed'])
        target['left:up'][0]['yellow']=True
        result=color_verdict(target,{'right:down'})
        self.assertFalse(result['passed']);self.assertEqual(result['unexpected_yellow_components'],['left:up'])
    def test_physical_only_pair_requires_no_yellow(self):
        self.assertTrue(color_verdict({},set())['passed'])
        self.assertFalse(color_verdict({'left:select':[{'yellow':True}]},set())['passed'])
