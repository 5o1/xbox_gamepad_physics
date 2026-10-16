"""Approved MuJoCo numerical policy, separate from hardware physical data."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

POLICY_RESOURCE = Path(__file__).resolve().parents[1] / 'build_data/calibration/mujoco_m2.json'


def _backend_options(options):
    defaults = json.loads(POLICY_RESOURCE.read_text())['backend_options']['mujoco']
    if options is not None and set(options) - set(defaults):
        raise ValueError('Unknown MuJoCo backend options')
    return defaults, {**defaults, **(options or {})}


def contact_policy(mujoco_options=None):
    """Resolve the trial geom-owned contact response, without caller mutation."""
    defaults, options = _backend_options(mujoco_options)
    policy = copy.deepcopy(options['contact_response'])
    if set(policy) - set(defaults['contact_response']):
        raise ValueError('Unknown MuJoCo contact response policy fields')
    if policy.get('schema_version') != 'mujoco-contact-response-v1' or policy.get('mujoco_version') != '3.16.0':
        raise ValueError('Contact response requires the reviewed schema and MuJoCo 3.16.0')
    if policy.get('approval_status') != 'trial_approved' or not policy.get('approval_date'):
        raise ValueError('Contact response requires recorded trial approval')
    for field in ('solref_time_constant_s', 'solmix_weight'):
        value = policy.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{field} must be finite and positive')
    if policy.get('solref_damping_ratio') != 1.0:
        raise ValueError('The trial contact policy retains damping ratio 1.0')
    return policy


def numerical_policy(mujoco_options=None, *, physics_timestep_s=None):
    """Resolve backend_options.mujoco and an optional finer diagnostic step.

    The approved bound is 0.0005 seconds; the frozen outer clock is 0.004.
    Finer integer subdivisions support the explicitly requested convergence
    experiment without changing the common probe-controller clock or physics.
    """
    defaults, options = _backend_options(mujoco_options)
    policy = copy.deepcopy(options['numerical_stability'])
    if set(policy) - (set(defaults['numerical_stability']) | {'diagnostic_refinement'}):
        raise ValueError('Unknown MuJoCo numerical stability policy fields')
    if policy.get('schema_version') != 'mujoco-substeps-v1' or policy.get('mujoco_version') != '3.16.0':
        raise ValueError('MuJoCo numerical policy requires the reviewed schema and version 3.16.0')
    if policy.get('approval_status') != 'approved' or policy.get('approval_date') != '2026-10-16':
        raise ValueError('MuJoCo numerical policy requires owner approval')
    if policy.get('integrator') != 'implicitfast':
        raise ValueError('The approved MuJoCo integrator is implicitfast')
    outer = policy.get('acceptance_step_s')
    if isinstance(outer, bool) or outer != .004:
        raise ValueError('The frozen acceptance timestep must remain 0.004 seconds')
    bound = policy.get('max_physics_timestep_s')
    if isinstance(bound, bool) or bound != .0005:
        raise ValueError('The approved maximum physics timestep is 0.0005 seconds')
    selected = policy.get('physics_timestep_s') if physics_timestep_s is None else physics_timestep_s
    if isinstance(selected, bool) or not isinstance(selected, (int, float)) or not math.isfinite(selected) or not 0 < selected <= bound:
        raise ValueError('Physics timestep must be positive and at most 0.0005 seconds')
    subdivisions = round(outer/selected)
    if not math.isclose(subdivisions*selected, outer, rel_tol=0., abs_tol=1e-15):
        raise ValueError('Physics timestep must exactly subdivide the frozen acceptance timestep')
    if physics_timestep_s is None and policy.get('substeps_per_acceptance_step') != subdivisions:
        raise ValueError('Numerical policy substep count does not match its timesteps')
    policy['physics_timestep_s'] = float(selected)
    policy['substeps_per_acceptance_step'] = subdivisions
    policy['diagnostic_refinement'] = physics_timestep_s is not None and selected != .0005
    return policy
