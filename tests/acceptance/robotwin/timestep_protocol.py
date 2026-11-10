"""Time resampling of the frozen 4 ms protocols; forces and criteria are unchanged."""
from dataclasses import replace

from tests.acceptance import load_suite


TIMESTEPS = (.001, .004)


def timing_table(timestep):
    """Return integer counts for the two accepted physical time grids."""
    if timestep not in TIMESTEPS:
        raise ValueError("formal RoboTwin acceptance supports 0.001 or 0.004 s")
    steps = lambda seconds: round(seconds / timestep)
    return {
        "dt_s": timestep,
        "settle_steps": steps(1),
        "T1": {"ramp_steps": steps(3), "samples": 2 * steps(3) + 1},
        "T2": {"hold_steps": steps(1), "stable_steps": steps(.5)},
        "cone": {"total_steps": steps(2), "load_steps": steps(1), "release_steps": steps(1)},
        "T3v2": {phase: steps(seconds) for phase, seconds in (
            ("settle", 1), ("ramp_up", .5), ("hold", 1),
            ("ramp_down", .5), ("observe", .5), ("stable", .5))},
        "T4": {"stable_steps": steps(.5), "blocked_intervals": steps(.1),
               "maximum_steps": steps(40)},
    }


def resample_suite(timestep, suite=None):
    """Select the physical clock without changing the frozen 4 ms source data."""
    table = timing_table(timestep)
    suite = load_suite() if suite is None else suite
    return replace(suite, fixture={**suite.fixture, "dt_s": timestep},
                   criteria={**suite.criteria, "hold_steps": table["T4"]["stable_steps"]})
