"""Native cone geometry, joint contact solving, and honest state observations."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from xbox_gamepad_physics.backends.common.handle import ResetRequest
from xbox_gamepad_physics.errors import StateValidationError
from xbox_gamepad_physics.mujoco.handle import MujocoGamepadHandle
from xbox_gamepad_physics.mujoco.limits import append_native_tilt_limits


MAXIMUM = math.radians(23)
DESCRIPTION = {
    'id': 'stick_limit', 'type': 'shaft_tilt_limit', 'enforcement': 'hard',
    'reference_link': 'controller_body', 'moving_link': 'tilt_y_frame',
    'pivot_in_reference_m': [0, 0, 0], 'pivot_in_moving_m': [0, 0, 0],
    'reference_axis': [0, 0, 1], 'moving_axis': [0, 0, 1],
    'max_angle_rad': MAXIMUM,
}


def _coordinates(theta, heading):
    return (math.atan2(math.sin(theta)*math.cos(heading), math.cos(theta)),
            -math.asin(math.sin(theta)*math.sin(heading)))


def _scene(*, free=False):
    """Numerical fixture parameters are test definitions, not hardware evidence."""
    mj = pytest.importorskip('mujoco')
    xml = ET.fromstring('''<mujoco><compiler angle="radian"/>
      <option timestep=".0005" integrator="implicitfast" gravity="0 0 0"/>
      <worldbody><body name="controller_body">
        <inertial mass=".1" pos="0 0 0" diaginertia=".001 .001 .001"/>
        <body name="tilt_x_frame"><joint name="tilt_x" axis="0 1 0"/>
          <inertial mass=".001" pos="0 0 0" diaginertia=".000001 .000001 .000001"/>
          <body name="tilt_y_frame"><joint name="tilt_y" axis="1 0 0"/>
            <inertial mass=".001" pos="0 0 0" diaginertia=".000001 .000001 .000001"/>
            <body name="stick"><joint name="click" type="slide" axis="0 0 -1"/>
              <inertial mass=".001" pos="0 0 .03" diaginertia=".000001 .000001 .000001"/>
              <geom name="cap" type="sphere" size=".004" pos="0 0 .03"/>
            </body>
          </body>
        </body>
      </body>
      <body name="probe" pos="1 0 0"><freejoint name="probe_free"/>
        <geom name="probe_geom" type="sphere" size=".004" mass=".05"/>
      </body></worldbody><actuator>
        <position name="return_tilt_x" joint="tilt_x" kp=".02" kv=".0001"/>
        <position name="return_tilt_y" joint="tilt_y" kp=".02" kv=".0001"/>
        <position name="return_click" joint="click" kp=".02" kv=".0001"/>
      </actuator></mujoco>''')
    if free:
        ET.SubElement(xml.find('worldbody/body'), 'freejoint', name='root_free')
    append_native_tilt_limits(xml, (DESCRIPTION,))
    model = mj.MjModel.from_xml_string(ET.tostring(xml, encoding='unicode'))
    data = mj.MjData(model)
    names = ('tilt_x', 'tilt_y', 'click')
    handle = MujocoGamepadHandle(model, data, joints={name: name for name in names},
        actuators={name: 'return_'+name for name in names}, sensors={}, signal_controller=None,
        root_body='controller_body', root_joint='root_free' if free else None,
        initial_positions=dict.fromkeys(names, 0.), neutral_targets=dict.fromkeys(names, 0.),
        hard_limits=(DESCRIPTION,))
    return mj, model, data, handle


@pytest.mark.parametrize('free', (False, True))
def test_native_geometry_matches_shaft_angle_and_click_is_independent(free):
    mj, model, data, handle = _scene(free=free)
    if free:
        data.joint('root_free').qpos[:3] = [.1, -.2, .3]
        mj.mju_axisAngle2Quat(data.joint('root_free').qpos[3:], np.array([0., 1., 0.]), .3)
    for degrees in (0., 10., 23., 26.):
        for heading in range(0, 360, 45):
            x, y = _coordinates(math.radians(degrees), math.radians(heading))
            data.joint('tilt_x').qpos[0], data.joint('tilt_y').qpos[0] = x, y
            lengths = []
            for click in (0., .0004):
                data.joint('click').qpos[0] = click
                mj.mj_forward(model, data)
                sample = handle.tilt_limit_state()['stick_limit']
                assert sample['angle_rad'] == pytest.approx(math.radians(degrees), abs=1e-14)
                lengths.append(float(data.ten_length[0]))
                assert lengths[-1] == pytest.approx(2*math.sin(sample['angle_rad']/2), abs=1e-14)
            assert lengths[0] == lengths[1]


@pytest.mark.parametrize('free', (False, True))
def test_contacts_and_tendon_limits_share_native_solve(free):
    mj, model, data, handle = _scene(free=free)
    data.joint('tilt_x').qpos[0] = MAXIMUM + .001
    mj.mj_forward(model, data)
    # Push outward into the cone boundary, rather than assist the return drive.
    data.joint('probe_free').qpos[:3] = data.geom('cap').xpos + [-.006, 0., 0.]
    mj.mj_forward(model, data)
    kinds = set(map(int, data.efc_type))
    assert int(mj.mjtConstraint.mjCNSTR_LIMIT_TENDON) in kinds
    assert any(kind >= int(mj.mjtConstraint.mjCNSTR_CONTACT_FRICTIONLESS) for kind in kinds)
    assert np.linalg.norm(data.qfrc_constraint[model.joint('probe_free').dofadr[0]:]) > 0
    if free:
        assert np.linalg.norm(data.qfrc_constraint[:6]) > 0
    mj.mj_step(model, data, nstep=8)
    assert np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all()
    assert not any(w.number for w in data.warning)


def test_explicit_outside_write_is_atomic_but_native_excess_remains_observable():
    _, _, data, handle = _scene()
    before, velocity = data.qpos.copy(), data.qvel.copy()
    with pytest.raises(StateValidationError, match='requested limit'):
        handle.set_joint_positions({'tilt_x': MAXIMUM, 'tilt_y': MAXIMUM})
    np.testing.assert_array_equal(data.qpos, before)
    np.testing.assert_array_equal(data.qvel, velocity)
    data.joint('tilt_x').qpos[0] = MAXIMUM + .01
    before = data.qpos.copy()
    assert handle.joint_positions()['tilt_x'] == MAXIMUM + .01
    assert handle.tilt_limit_state()['stick_limit']['excess_rad'] == pytest.approx(.01)
    np.testing.assert_array_equal(data.qpos, before)
    np.testing.assert_array_equal(data.qvel, velocity)


def test_reset_preserves_requested_velocity_without_a_separate_impulse():
    _, _, data, handle = _scene()
    handle.reset(ResetRequest(joint_positions={'tilt_x': MAXIMUM-1e-14},
        joint_velocities={'tilt_x': 1., 'tilt_y': .3, 'click': 0.}))
    assert data.joint('tilt_x').qvel[0] == 1.
    assert data.joint('tilt_y').qvel[0] == .3
