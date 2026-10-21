"""Native cone geometry, read-only state validation and unmodified stepping."""
from dataclasses import replace
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from xbox_gamepad_physics.builders.build_common_motion import build
from xbox_gamepad_physics.isaac.constraints import require_supported_constraints
from xbox_gamepad_physics.motion import motion_from_dict


@pytest.fixture
def required_motion(tmp_path):
    pytest.importorskip('xbox_gamepad_physics.backends.common.constraints', reason='requires the separate common shaft-limit patch')
    prepared = os.environ.get('XGP_B2_MOTION')
    raw = json.loads(Path(prepared).read_text()) if prepared else build(tmp_path/'motion.json')
    raw['joint_space_constraints'] = [c for c in raw['joint_space_constraints'] if c.get('enforcement') != 'hard']
    for side in ('left', 'right'):
        raw['joint_space_constraints'].append({
            'id': side+'_stick_circular_limit', 'type': 'shaft_tilt_limit',
            'enforcement': 'hard', 'reference_link': 'controller_body',
            'moving_link': side+'_stick_y_frame',
            'reference_axis': [0., 0., 1.], 'moving_axis': [0., 0., 1.],
            'max_angle_rad': math.radians(23.)})
    return motion_from_dict(raw)


def bound_geometry(motion):
    torch = pytest.importorskip('torch')
    from xbox_gamepad_physics.isaac.shaft_limits import ShaftLimits
    q = torch.zeros((5, len(motion.joints)), dtype=torch.float32)
    names = tuple(motion.joint_by_name)
    art = SimpleNamespace(device='cpu', data=SimpleNamespace(joint_pos=q),
                          is_fixed_base=False, joint_names=names)
    return ShaftLimits(art, motion), q, names


def test_actual_cone_and_gradient(required_motion):
    torch = pytest.importorskip('torch')
    limit, q, names = bound_geometry(required_motion)
    i, j = [names.index('left_stick_'+axis) for axis in ('x', 'y')]
    q = q.double()
    q[:, i] = torch.tensor([0., .2, -.3, .4014257279586958, .4014257279586958], dtype=q.dtype)
    q[:, j] = torch.tensor([0., -.3, .1, 0., .4014257279586958], dtype=q.dtype)
    angle, gradient = limit.geometry(q)
    assert math.degrees(angle[-1, 0]) == pytest.approx(32.077645709617485)
    # Compare the optimized current chain to generic quaternion composition.
    limit._fast = False
    generic_angle, generic_gradient = limit.geometry(q)
    torch.testing.assert_close(angle, generic_angle, atol=3e-16, rtol=1e-14)
    torch.testing.assert_close(gradient, generic_gradient, atol=3e-16, rtol=1e-14)
    for column in (i, j):
        plus, minus = q.clone(), q.clone()
        plus[:, column] += 1e-6; minus[:, column] -= 1e-6
        derivative = (limit.geometry(plus)[0]-limit.geometry(minus)[0])/2e-6
        torch.testing.assert_close(derivative, gradient[:, :, column], atol=1e-10, rtol=1e-9)
    # Click is downstream from the shaft frame and must not change its cone.
    q[:, names.index('left_stick_click')] = -.001
    torch.testing.assert_close(limit.geometry(q)[0], angle)


def test_native_storage_and_outward_boundary_writes(required_motion):
    torch = pytest.importorskip('torch')
    limit, q, names = bound_geometry(required_motion)
    i, j = [names.index('left_stick_'+axis) for axis in ('x', 'y')]
    q[:, i] = math.radians(23.)
    original = q.clone()
    clean = limit.checked_state(q, torch.zeros_like(q))
    assert clean is q
    assert bool((limit.geometry(clean)[0] <= limit.maximum).all())
    torch.testing.assert_close(q, original, atol=0., rtol=0.)
    v = torch.zeros_like(q); v[:, i] = 1.
    with pytest.raises(ValueError, match='outward'):
        limit.checked_state(q, v)
    v[:, i] = -1.
    assert bool((limit.geometry(limit.checked_state(q, v))[0] <= limit.maximum).all())
    v[:, i] = 0.; v[:, j] = 1.
    tangent = v.clone()
    limit.checked_state(q, v)
    torch.testing.assert_close(v, tangent, atol=0., rtol=0.)
    q[:, j] = math.radians(23.)
    with pytest.raises(ValueError, match='hard shaft cone'):
        limit.checked_state(q, torch.zeros_like(q))
    assert limit.checked_state(q[:0], v[:0]).shape == q[:0].shape


def test_binding_validation_does_not_rewrite_native_state(required_motion):
    torch = pytest.importorskip('torch')
    limit, q, names = bound_geometry(required_motion)
    q[:, names.index('left_stick_x')] = math.radians(23.)
    original = q.clone()
    art = limit.articulation
    art.data.joint_vel = torch.zeros_like(q)
    writes = []
    art.write_joint_state_to_sim = lambda *args: writes.append(args)
    limit.validate_initial_state()
    assert writes == []
    torch.testing.assert_close(q, original, atol=0., rtol=0.)


def test_native_step_preserves_solver_results_without_projection():
    from xbox_gamepad_physics.isaac.stepping import step
    calls = []
    native = {'angle_deg': 0., 'velocity': 0.}

    def forbidden():
        raise AssertionError('stepping must not call a custom constraint solver')

    def advance(*, render):
        calls.append(('physics', render))
        native.update(angle_deg=23.04, velocity=.12)

    art = SimpleNamespace(write_data_to_sim=lambda: calls.append('flush'),
                          update=lambda dt: calls.append(('update', dt)))
    handle = SimpleNamespace(articulation=art, _shaft_limits=SimpleNamespace(enforce=forbidden))
    simulation = SimpleNamespace(get_physics_dt=lambda: .004, step=advance,
                                 render=lambda: calls.append('render'))
    step(simulation, gamepads=(handle,), nstep=2, render=True)
    assert native == {'angle_deg': 23.04, 'velocity': .12}
    assert calls == ['flush', ('physics', False), ('update', .004), 'render']*2


def test_press_sample_reports_native_residual_without_state_changes(required_motion):
    torch = pytest.importorskip('torch')
    from xbox_gamepad_physics.backends.common.model import Pose
    from xbox_gamepad_physics.isaac.press import IsaacPressExecutor
    limits, q, names = bound_geometry(required_motion)
    q[:, names.index('left_stick_x')] = math.radians(23.04)
    v = torch.zeros_like(q)
    v[:, names.index('left_stick_x')] = .1
    limits.articulation.data.joint_vel = v
    original = q.clone()
    pad = SimpleNamespace(articulation=limits.articulation, motion=required_motion,
        _shaft_limits=limits, joint_positions=lambda: dict(zip(names, q[0].tolist())), root_pose=Pose)
    probe_state = torch.zeros((1, 13)); probe_state[:, 3] = 1.
    probe = SimpleNamespace(data=SimpleNamespace(root_state_w=probe_state))
    executor = IsaacPressExecutor(simulation=None, gamepad=pad, probe=probe, sensors={},
        root_pose=Pose(), radius_m=.003)
    sample = executor.sample()
    diagnostic = sample['shaft_limits']
    assert diagnostic['state_projection'] is False
    assert diagnostic['maximum_excess_rad'][0] > 0.
    assert diagnostic['maximum_boundary_outward_rad_s'] > 0.
    assert diagnostic['impulse_n_m_s'] is None
    assert sample['joint_positions']['left_stick_x'] > math.radians(23.)
    torch.testing.assert_close(q, original, atol=0., rtol=0.)


def test_invalid_initial_state_is_rejected_before_native_write(required_motion, tmp_path):
    torch = pytest.importorskip('torch')
    from xbox_gamepad_physics.isaac.articulation import make_articulation_cfg
    limit, q, names = bound_geometry(required_motion)
    for axis in ('x', 'y'):
        q[:, names.index('left_stick_'+axis)] = math.radians(23.)
    art = limit.articulation
    art.data.joint_vel = torch.zeros_like(q)
    writes = []
    art.write_joint_state_to_sim = lambda *args: writes.append(args)
    with pytest.raises(ValueError, match='hard shaft cone'):
        limit.validate_initial_state()
    assert writes == []
    laws = {name: SimpleNamespace(initial_position=SimpleNamespace(value=float(q[0, i])))
            for i, name in enumerate(names)}
    with pytest.raises(ValueError, match='initial position'):
        make_articulation_cfg(tmp_path/'absent.usda', motion=required_motion,
                              physical=SimpleNamespace(return_laws=laws))


def test_unknown_hard_constraint_errors_before_platform_work(required_motion, tmp_path):
    from xbox_gamepad_physics.isaac import build_usd
    unknown = replace(required_motion, joint_space_constraints=({'id': 'new_stop', 'enforcement': 'hard', 'type': 'unknown'},))
    with pytest.raises(NotImplementedError, match='new_stop'):
        build_usd(tmp_path/'missing.usda', motion=unknown, physical=None,
                  appearance=None, collision_sources=(), visual_directory=tmp_path)
    assert not (tmp_path/'missing.usda').exists()


def test_shared_value_and_legacy_contract(required_motion):
    from xbox_gamepad_physics.backends.common.constraints import ShaftTiltLimit
    values = require_supported_constraints(required_motion)
    assert len(values) == 2 and all(isinstance(x, ShaftTiltLimit) for x in values)
    legacy = replace(required_motion, joint_space_constraints=tuple(
        c for c in required_motion.joint_space_constraints if c.get('enforcement') != 'hard'))
    assert require_supported_constraints(legacy) == ()
