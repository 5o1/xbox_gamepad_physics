"""Physical-duration resampling retains frozen thresholds, forces and 4 ms behavior."""
from copy import deepcopy
import unittest

from tests.acceptance import load_suite, PressTrajectory, run_case
from tests.acceptance.robotwin.timestep_protocol import resample_suite, timing_table
from tests.acceptance.scoring import score_case


class TimestepProtocolTest(unittest.TestCase):
    def test_conversion_table_for_both_frozen_grids(self):
        slow = timing_table(.004)
        fast = timing_table(.001)
        self.assertEqual(slow["settle_steps"], 250)
        self.assertEqual(fast["settle_steps"], 1000)
        self.assertEqual(slow["T1"], {"ramp_steps": 750, "samples": 1501})
        self.assertEqual(fast["T1"], {"ramp_steps": 3000, "samples": 6001})
        self.assertEqual(fast["T2"], {"hold_steps": 1000, "stable_steps": 500})
        self.assertEqual(fast["cone"], {"total_steps": 2000, "load_steps": 1000, "release_steps": 1000})
        self.assertEqual(fast["T3v2"], dict(settle=1000, ramp_up=500, hold=1000,
                                         ramp_down=500, observe=500, stable=500))
        self.assertEqual(fast["T4"], dict(stable_steps=500, blocked_intervals=100, maximum_steps=40000))
        for name in ("T2", "cone", "T3v2", "T4"):
            self.assertEqual(fast[name], {key: count * 4 for key, count in slow[name].items()})
        with self.assertRaises(ValueError):
            timing_table(.002)

    def test_resampling_leaves_4ms_suite_and_physics_unchanged(self):
        frozen = load_suite()
        before = deepcopy(frozen)
        self.assertEqual(resample_suite(.004, frozen), frozen)
        fast = resample_suite(.001, frozen)
        self.assertEqual(frozen, before)
        self.assertEqual(fast.fixture, {**frozen.fixture, "dt_s": .001})
        self.assertEqual(fast.criteria, {**frozen.criteria, "hold_steps": 500})
        for name in ("cases", "settings", "press_stop", "evidence"):
            self.assertEqual(getattr(fast, name), getattr(frozen, name))
        self.assertEqual(fast.settings["radius_m"], .004)
        self.assertEqual(fast.settings["mass_kg"], .05)

    def test_trajectory_hold_and_blocked_clock_use_selected_dt(self):
        for dt in (.001, .004):
            with self.subTest(dt=dt):
                suite = resample_suite(dt)
                trajectory = PressTrajectory(suite, suite.case("A"))
                self.assertEqual(trajectory.dt, dt)
                self.assertEqual(trajectory.stop.window_steps, round(.1 / dt))
                trajectory.enter("hold", 0)
                trajectory.before_step(round(.5 / dt) - 1)
                self.assertEqual(trajectory.phase, "hold")
                trajectory.before_step(round(.5 / dt))
                self.assertEqual(trajectory.phase, "withdraw")

    def test_scoring_preserves_physical_return_time_and_half_second_window(self):
        results = []
        for dt in (.001, .004):
            suite = resample_suite(dt)
            case = suite.case("A")
            rows = []
            # Early hold fails the signal target; the final 0.5 s passes.
            for step in range(round(.75 / dt)):
                rows.append({"step": step, "signals": {"south": 0. if step < round(.25 / dt) else 1.},
                             "probe": {"phase": "hold", "phase_age_s": step * dt, "events": {}},
                             "gamepad_internal_pairs": 0})
            for index in range(round(.5 / dt)):
                rows.append({"step": len(rows), "signals": {"south": 1. if index < round(.2 / dt) else 0.},
                             "probe": {"phase": "observe", "phase_age_s": index * dt, "events": {}},
                             "gamepad_internal_pairs": 0})
            result = score_case(suite, case, rows)
            self.assertTrue(result["physics_passed"])
            self.assertAlmostEqual(result["return_time_after_withdraw_s"], .2)
            # The count rounds differently at 4 ms, with duration error <= dt.
            self.assertAlmostEqual(result["hold_sim_seconds"], .75, delta=dt)
            results.append(result)
            with self.assertRaises(ValueError):
                score_case(suite, case, rows[:round(.5 / dt)-1])
        for key in ("target_min", "target_max", "target_threshold", "signal_passed", "no_misfires",
                    "return_time_after_withdraw_s", "return_passed", "internal_pairs", "physics_passed"):
            self.assertEqual(results[0][key], results[1][key])

    def test_runner_steps_and_phase_ages_follow_fixture_without_native_engine(self):
        class Sink:
            def __init__(self): self.rows = []
            def write(self, row): self.rows.append(row)

        class Executor:
            def __init__(self): self.steps = []
            def reset_case(self, suite, case): self.case = case
            def ball_state(self):
                return {"position_m": self.case.plan["start_m"], "velocity_m_s": [0, 0, 0]}
            def apply_ball_force(self, force): pass
            def step(self, dt): self.steps.append(dt)
            def sample(self):
                return {"signals": {"south": 1.}, "probe": {"pose": [0, 0, 0], "events": {}},
                        "gamepad_internal_pairs": 0}

        for dt in (.001, .004):
            with self.subTest(dt=dt):
                suite = resample_suite(dt)
                sink, executor = Sink(), Executor()
                result = run_case(executor, suite, suite.case("A"), sink)
                self.assertEqual(set(executor.steps), {dt})
                self.assertAlmostEqual(len(executor.steps) * dt, 2.5, delta=5 * dt)
                hold = [row for row in sink.rows if row["probe"]["phase"] == "hold"
                        and row["probe"]["phase_age_s"] >= 0]
                self.assertEqual(len(hold), round(.5 / dt))
                self.assertEqual(result["hold_sim_seconds"], .5)
                self.assertTrue(result["signal_passed"])


if __name__ == "__main__":
    unittest.main()
