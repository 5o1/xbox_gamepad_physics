"""The approved backend numerical policy stays outside hardware parameters."""
import copy
import pytest
from xbox_gamepad_physics.mujoco.numerics import numerical_policy


def test_approved_policy_and_finer_convergence_subdivision():
    policy = numerical_policy()
    assert policy['approval_status'] == 'approved'
    assert policy['approval_date'] == '2026-10-20'
    assert policy['integrator'] == 'discrete'
    assert policy['refsafe'] is False
    assert policy['substeps_per_acceptance_step'] == 8
    finer = numerical_policy(physics_timestep_s=.00025)
    assert finer['substeps_per_acceptance_step'] == 16
    assert finer['acceptance_step_s'] == .004
    assert numerical_policy()['physics_timestep_s'] == .0005


def test_reject_changed_fixture_unapproved_or_unsafe_numerical_policy():
    policy = numerical_policy()
    for field, value in [('approval_status', 'pending_owner_approval'),
                         ('acceptance_step_s', .002), ('physics_timestep_s', .004)]:
        changed = copy.deepcopy(policy)
        changed[field] = value
        with pytest.raises(ValueError):
            numerical_policy({'numerical_stability': changed})
    with pytest.raises(ValueError, match='subdivide'):
        numerical_policy(physics_timestep_s=.0003)
