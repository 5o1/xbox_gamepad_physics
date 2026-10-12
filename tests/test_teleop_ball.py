"""Contact-test semantics and exact canonical serialization, without SAPIEN."""
import unittest
from teleop.ball_probe import CASES,case_spec,target_value,misfires,threshold,PressStop,SETTINGS
from teleop.session import canonical_data
from xbox_gamepad_physics.state import GamepadState,XBOX_ONE_S_CHANNELS


class SphereAcceptanceTest(unittest.TestCase):
    def test_press_continues_past_scoring_threshold_and_stops_at_goal(self):
        stop=PressStop(SETTINGS)
        self.assertIsNone(stop.sample(0,.9,.005,.004,2))
        self.assertIsNone(stop.sample(1,.95,.006,.005,2))
        self.assertEqual(stop.sample(2,.98,.007,.006,2)['reason'],'signal_goal')

    def test_blocked_requires_full_stationary_window_and_near_limit_force(self):
        stop=PressStop(SETTINGS)
        for step in range(25):self.assertIsNone(stop.sample(step,.2,.010,.005,16))
        result=stop.sample(25,.2,.011,.005,16)
        self.assertEqual(result['reason'],'blocked')
        self.assertEqual(result['window_steps'],25)
        low_force=PressStop(SETTINGS)
        moving=PressStop(SETTINGS)
        for step in range(30):
            self.assertIsNone(low_force.sample(step,.2,.010,.005,15.1))
            self.assertIsNone(moving.sample(step,.2,.010,step*2e-6,16))

    def test_maximum_stroke_stops_when_neither_goal_nor_blocked(self):
        result=PressStop(SETTINGS).sample(0,.1,.030,.020,16)
        self.assertEqual(result['reason'],'maximum_stroke')
        self.assertEqual(result['stroke_m'],.030)

    def test_hold_target_fixed_and_withdrawal_does_not_wait_for_browser(self):
        from types import SimpleNamespace
        import numpy as np
        from teleop.ball_probe import BallProbe
        probe=BallProbe.__new__(BallProbe)
        probe.settings=SETTINGS;probe.session=SimpleNamespace(index=100)
        probe.phase='hold';probe.phase_start=0;probe.target=np.array([0.,0.,-.010])
        probe.plan={'start_m':[0,0,.005],'direction':[0,0,-1]}
        probe.body=SimpleNamespace(pose=SimpleNamespace(p=np.zeros(3)),linear_velocity=np.zeros(3),add_force_at_point=lambda *args:None)
        probe.before_step();self.assertEqual(probe.phase,'hold')
        np.testing.assert_array_equal(probe.target,[0,0,-.010])
        probe.session.index=125;probe.before_step()
        self.assertEqual(probe.phase,'withdraw')
        np.testing.assert_array_equal(probe.target,[0,0,-.010])

    def test_case_coverage_includes_each_signed_axis_and_pair(self):
        self.assertEqual(len(CASES),26)
        mapped={case_spec(n)['channel'] for n in CASES}
        self.assertEqual(mapped-{None},set(XBOX_ONE_S_CHANNELS))
        self.assertIn(None,mapped)
        signals=dict.fromkeys(XBOX_ONE_S_CHANNELS,0)
        signals['left_x']=-.95
        self.assertEqual(target_value(case_spec('left_x_neg'),signals,{}),.95)
        self.assertEqual(target_value(case_spec('Pair'),signals,{'pair_bind_connect':1}),1)
        signals.update(dpad_up=.96,dpad_left=.97)
        self.assertEqual(target_value(case_spec('Dpad_up'),signals,{}),.96)
        self.assertEqual(target_value(case_spec('Dpad_left'),signals,{}),.97)

    def test_radial_coupling_does_not_exempt_click_or_opposite_stick(self):
        signals=dict.fromkeys(XBOX_ONE_S_CHANNELS,0)
        signals.update(left_x=.9,left_y=.92,right_y=.95,left_stick=1)
        self.assertEqual(set(misfires(case_spec('left_x_pos'),signals)),{'right_y','left_stick'})
        self.assertEqual(threshold('left_trigger'),.9)
        self.assertEqual(threshold('south'),.95)

    def test_complete_loader_state_and_masks_survive_serialization(self):
        state=GamepadState.xbox_one_s({'south':.96},task_channels=['south'])
        frame=canonical_data(state)
        self.assertEqual(tuple(frame['values']),state.values)
        self.assertEqual(tuple(frame['available_mask']),state.available_mask)
        self.assertEqual(tuple(frame['task_mask']),state.task_mask)
        self.assertEqual(len(frame['values']),32)
        self.assertEqual(frame['layout_id'],'sdl3-gamepad-core-v1')
