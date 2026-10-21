"""The approved backend numerical policy stays outside hardware parameters."""
import copy
import pytest
from xbox_gamepad_physics.mujoco.numerics import numerical_policy


def test_approved_policy_and_finer_convergence_subdivision():
    policy = numerical_policy()
    assert policy['integrator'] == 'discrete'
    assert policy['refsafe'] is False
    assert policy['substeps_per_acceptance_step'] == 8
    finer = numerical_policy(physics_timestep_s=.00025)
    assert finer['substeps_per_acceptance_step'] == 16
    assert finer['acceptance_step_s'] == .004
    assert numerical_policy()['physics_timestep_s'] == .0005


def test_reject_changed_fixture_unapproved_or_unsafe_numerical_policy():
    policy = numerical_policy()
    for field, value in [('acceptance_step_s', .002), ('physics_timestep_s', .004)]:
        changed = copy.deepcopy(policy)
        changed[field] = value
        with pytest.raises(ValueError):
            numerical_policy({'numerical_stability': changed})
    with pytest.raises(ValueError, match='subdivide'):
        numerical_policy(physics_timestep_s=.0003)


def test_approval_annotations_do_not_control_execution():
    policy = numerical_policy()
    policy.pop('approval_status')
    policy.pop('approval_date')
    assert numerical_policy({'numerical_stability': policy})['physics_timestep_s'] == .0005
