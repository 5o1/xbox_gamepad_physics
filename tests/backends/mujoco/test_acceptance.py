"""Probe dynamics and archive guarantees, independent of large source meshes."""
from types import SimpleNamespace

import pytest

from xbox_gamepad_physics.acceptance import load_suite
from xbox_gamepad_physics.backends.common.model import Pose
from xbox_gamepad_physics.mujoco.acceptance import MujocoPressExecutor, execute_suite, fixture_mapping
from xbox_gamepad_physics.state import GamepadState


class NeutralHandle:
    def restore_passive_targets(self):
        pass

    def gamepad_state(self):
        return GamepadState.xbox_one_s()

    def physical_events(self):
        return {"pair_bind_connect": 0.0}

    def joint_positions(self):
        return {name: 0.0 for name in load_suite().cases[0].joint_limits}

    def joint_velocity(self, name):
        return 0.0

    def root_pose(self):
        return Pose()

    def root_twist(self):
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def empty_asset(**kwargs):
    import mujoco
    spec = mujoco.MjSpec.from_string("<mujoco/>")
    return SimpleNamespace(spec=spec, bind=lambda model, data: NeutralHandle())


def test_force_actuators_obey_fixture_mass_and_gravity():
    pytest.importorskip("mujoco")
    suite = load_suite()
    executor = MujocoPressExecutor(spec_factory=empty_asset)
    executor.reset_case(suite, suite.cases[0])
    assert executor.mapping['probe_native_contact']['solref'] == [.02,1.]
    assert executor.mapping['probe_native_contact']['solmix'] == 1.
    initial = executor.ball_state()["position_m"]
    executor.apply_ball_force((0, 0, suite.settings["mass_kg"] * 9.81))
    for _ in range(20):
        executor.step(0.004)
    assert executor.ball_state()["position_m"] == pytest.approx(initial, abs=1e-12)
    executor.apply_ball_force((1, 0, suite.settings["mass_kg"] * 9.81))
    executor.step(0.004)
    assert executor.ball_state()["velocity_m_s"][0] == pytest.approx(1 / suite.settings["mass_kg"] * 0.004)
    assert executor.sample()["contacts"] == []
    assert executor.sample()["gamepad_internal_pairs"] == 0
    with pytest.raises(ValueError, match="total norm"):
        executor.apply_ball_force((16, 16, 0))
    with pytest.raises(ValueError, match="timestep"):
        executor.step(0.002)


def test_fixture_mapping_does_not_claim_physical_contact_equivalence():
    mapping = fixture_mapping(load_suite())
    assert mapping["physical_contact_mapping"] is None
    assert mapping["unmapped"]["sphere_material"]["static_friction"] == 0.8
    assert mapping["inertia_kg_m2"] == pytest.approx(2 * 0.05 * 0.004 ** 2 / 5)
    assert mapping['substeps_per_acceptance_step'] == 8
    assert mapping['physics_timestep_s'] == .0005


@pytest.mark.parametrize('physics_dt, count', [(None, 8), (.00025, 16)])
def test_native_substeps_hold_force_and_preserve_outer_clock(monkeypatch, physics_dt, count):
    mj = pytest.importorskip('mujoco')
    suite = load_suite()
    executor = MujocoPressExecutor(spec_factory=empty_asset, physics_timestep_s=physics_dt)
    executor.reset_case(suite, suite.cases[0])
    executor.apply_ball_force((1., 0., suite.settings['mass_kg'] * 9.81))
    command = executor.data.ctrl.copy()
    native_step = mj.mj_step
    calls = []
    def checked(model, data):
        assert (data.ctrl == command).all()
        calls.append(True)
        native_step(model, data)
    monkeypatch.setattr(mj, 'mj_step', checked)
    executor.step(.004)
    assert len(calls) == count
    assert executor.data.time == pytest.approx(.004)
    assert executor.step_performance()['substeps_per_acceptance_step'] == count
    assert executor.sample()['acceptance_step_wall_seconds'] > 0


def test_execution_error_keeps_remaining_cases_null(tmp_path, monkeypatch):
    def fail(self, suite, case):
        raise RuntimeError("fixture construction failed")
    monkeypatch.setattr(MujocoPressExecutor, "reset_case", fail)
    with pytest.raises(RuntimeError, match="fixture construction"):
        execute_suite(tmp_path)
    import json
    result = json.loads((tmp_path / "results.json").read_text())
    assert result["summary"]["attempted"] == 1
    assert result["summary"]["completed"] == 0
    assert result["results"][0]["status"] == "execution_error"
    assert all(r["physics_passed"] is None for r in result["results"])
    assert all(r["status"] == "not_run" for r in result["results"][1:])
