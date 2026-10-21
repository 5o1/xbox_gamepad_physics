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
    if policy.get('integrator') not in {'implicitfast', 'discrete'}:
        raise ValueError('Supported numerical policy integrators are implicitfast and discrete')
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


def limit_policy(mujoco_options=None):
    """Resolve the owner-selected tendon response, separate from contact geoms."""
    _, options = _backend_options(mujoco_options)
    return copy.deepcopy(options['limit_response'])


def standalone_option_attributes(policy):
    """Serialize the same standalone settings used by the native spec loader."""
    return {
        'timestep': str(policy['physics_timestep_s']), 'integrator': policy['integrator'],
        'solver': policy.get('solver', 'Newton'),
        'iterations': str(policy.get('iterations', 100)),
        'tolerance': str(policy.get('tolerance', 1e-8)),
    }


def standalone_flag_attributes(policy):
    return {'refsafe': 'enable' if policy.get('refsafe', True) else 'disable',
            'diagexact': 'enable' if policy.get('diagexact', False) else 'disable'}


def apply_standalone_policy(option, policy):
    """Apply numerical settings only to an owned standalone/acceptance model."""
    from ._backend import require_mujoco
    mj = require_mujoco()
    option.timestep = policy['physics_timestep_s']
    option.integrator = {'implicitfast': mj.mjtIntegrator.mjINT_IMPLICITFAST,
                         'discrete': mj.mjtIntegrator.mjINT_DISCRETE}[policy['integrator']]
    option.solver = getattr(mj.mjtSolver, 'mjSOL_' + policy.get('solver', 'Newton').upper())
    option.iterations = policy.get('iterations', 100)
    option.tolerance = policy.get('tolerance', 1e-8)
    refsafe = int(mj.mjtDisableBit.mjDSBL_REFSAFE)
    exact = int(mj.mjtEnableBit.mjENBL_DIAGEXACT)
    option.disableflags = ((int(option.disableflags) & ~refsafe) if policy.get('refsafe', True)
                           else (int(option.disableflags) | refsafe))
    option.enableflags = ((int(option.enableflags) | exact) if policy.get('diagexact', False)
                          else (int(option.enableflags) & ~exact))


def sdf_policy(mujoco_options=None):
    """Resolve native SDF representation and standalone search settings."""
    defaults, options = _backend_options(mujoco_options)
    policy = copy.deepcopy(options['sdf'])
    if set(policy) - set(defaults['sdf']):
        raise ValueError('Unknown MuJoCo SDF policy fields')
    if policy.get('schema_version') != 'mujoco-native-sdf-v1' or policy.get('mujoco_version') != '3.16.0':
        raise ValueError('Native SDF requires the reviewed schema and MuJoCo 3.16.0')
    if policy.get('default_collision') != 'sdf':
        raise ValueError('Native SDF is the default collision representation')
    for field in ('octree_maxdepth', 'sdf_iterations', 'sdf_initpoints'):
        if type(policy.get(field)) is not int or policy[field] <= 0:
            raise ValueError(f'{field} must be a positive integer')
    return policy
