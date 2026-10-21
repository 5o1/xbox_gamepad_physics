"""Frozen plans and phase clocks are lossless; physical scoring retains ruling20."""
import json
import math
from pathlib import Path
import unittest

from tests.acceptance import load_suite, PressStop, PressTrajectory, ball_force
from tests.acceptance.scoring import score_case
from tests.acceptance.records import summarize
from xbox_gamepad_physics.backends.common.model import Pose

ROOT=Path(__file__).resolve().parents[1]


class FrozenAcceptanceTest(unittest.TestCase):
    def test_data_has_26_sources_and_preserves_failed_cases(self):
        suite=load_suite()
        self.assertEqual(len(suite.cases),26)
        self.assertEqual([c.case_id for c in suite.cases if not c.baseline['passed']],['Pair','L3','R3'])
        for case in suite.cases:
            self.assertEqual(case.plan,case.at_pose(case.root_pose))
            self.assertTrue(case.source_paths['plan'].endswith('/'+case.case_id+'/server/ball_plan.json'))
        self.assertEqual(suite.criteria['dpad_threshold'],.3)
        self.assertEqual(suite.settings['force_limit_n'],16.)

    def test_historical_points_directions_steps_and_scores(self):
        suite=load_suite()
        for case in suite.cases:
            with self.subTest(case=case.case_id):
                source=ROOT/case.source_paths['plan']
                if not source.is_file():
                    self.skipTest('Historical checkout archive is not present')
                original=json.loads(source.read_text())
                self.assertEqual(original['plan'],dict(case.plan))
                self.assertEqual(original['gamepad_joint_limits'],dict(case.joint_limits))
                trace=[json.loads(line) for line in (ROOT/case.source_paths['timeline']).read_text().splitlines()]
                replay=list(case.replay_steps())
                self.assertEqual(len(replay),len(trace))
                for a,b in zip(replay,trace):
                    self.assertEqual(a['step'],b['step'])
                    self.assertEqual(a['phase'],b['probe']['phase'])
                    self.assertEqual(a['phase_age_s'],b['probe']['phase_age_s'])
                actual=score_case(suite,case,trace)
                for key in ('target_min','target_max','target_threshold','return_time_after_withdraw_s','internal_pairs','hold_sim_seconds','termination','joint_limit_excess'):
                    self.assertEqual(actual[key],case.baseline[key],key)
                self.assertEqual(actual['physics_passed'],case.baseline['passed'])

    def test_stop_order_requires_both_blocked_conditions(self):
        suite=load_suite();stop=PressStop(suite.settings,suite.press_stop)
        for index in range(25):self.assertIsNone(stop.sample(index,.2,.01,0.,16.))
        self.assertEqual(stop.sample(25,.2,.01,0.,16.)['reason'],'blocked')
        for force,progress in ((1.,0.),(16.,1e-3)):
            stop=PressStop(suite.settings,suite.press_stop)
            for index in range(30):result=stop.sample(index,.2,.01,index*progress,force)
            self.assertIsNone(result)
        self.assertEqual(stop.sample(31,.99,.03,0.,16.)['reason'],'signal_goal')

    def test_total_ball_force_is_clipped_after_gravity(self):
        suite=load_suite()
        force=ball_force(suite.settings,(0,0,1),(0,0,0),(0,0,0))
        self.assertAlmostEqual(math.sqrt(sum(v*v for v in force)),16.)
        self.assertEqual(ball_force(suite.settings,(0,0,0),(0,0,0),(0,0,0)),(0.,0.,.49050000000000005))

    def test_fixed_hold_does_not_depend_on_browser_and_null_denominators(self):
        suite=load_suite();trajectory=PressTrajectory(suite,suite.case('A'))
        for step in range(252):trajectory.before_step(step)
        trajectory.after_step(251,.99,trajectory.target,(0,0,1))
        self.assertEqual(trajectory.phase,'hold')
        for step in range(252,377):trajectory.before_step(step)
        self.assertEqual(trajectory.phase,'hold')
        trajectory.before_step(377)
        self.assertEqual(trajectory.phase,'withdraw')
        result=summarize([{'status':'passed'},{'status':'not_run'},{'status':'execution_error'}])
        self.assertEqual((result['planned'],result['attempted'],result['completed']),(26,2,1))


if __name__=='__main__':unittest.main()
