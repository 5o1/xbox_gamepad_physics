"""Native downstream-contact boundaries on synthetic spheres, not Xbox data."""
import pytest
from xbox_gamepad_physics.mujoco.numerics import contact_policy, numerical_policy


def test_trial_policy_and_explicit_contact_override_keep_outer_clock():
    policy = contact_policy()
    assert policy['approval_status'] == 'trial_approved'
    assert policy['approval_date'] == '2026-10-17'
    options = {'contact_response': {**policy, 'solref_time_constant_s': .001}}
    assert contact_policy(options)['solref_time_constant_s'] == .001
    assert numerical_policy(options)['acceptance_step_s'] == .004
    assert numerical_policy(options)['substeps_per_acceptance_step'] == 8


@pytest.mark.parametrize('other_friction', [(1.,.005,.0001),(.2,.02,.002)])
def test_native_solmix_weights_reference_and_impedance_not_friction(other_friction):
    mj = pytest.importorskip('mujoco')
    import numpy as np
    policy=contact_policy()
    def compile_contact(weight):
        # Synthetic geometry is only a fixture for the native mixing formula.
        xml=f'''<mujoco><option timestep=".0005" integrator="implicitfast"/>
        <worldbody><geom name="pad" type="sphere" size=".01" solref=".002 1"
          solmix="{weight}" friction="1 .005 .0001"/>
        <body pos="0 0 .018"><freejoint/><geom name="caller" type="sphere" size=".01"
          friction="{' '.join(map(str,other_friction))}"/></body></worldbody></mujoco>'''
        model=mj.MjModel.from_xml_string(xml);data=mj.MjData(model);mj.mj_forward(model,data)
        assert data.ncon == 1
        np.testing.assert_array_equal(model.geom('caller').solref,[.02,1.])
        assert float(model.geom('caller').solmix[0]) == 1.
        return data.contact[0].solref.copy(),data.contact[0].friction.copy()
    old_ref,old_friction=compile_contact(1.)
    new_ref,new_friction=compile_contact(policy['solmix_weight'])
    weight=policy['solmix_weight']
    expected=(weight*.002+.02)/(weight+1.)
    assert new_ref[0] == pytest.approx(expected,abs=1e-15)
    assert old_ref[0] == pytest.approx(.011)
    np.testing.assert_array_equal(old_friction,new_friction)
    coeff=np.maximum([1.,.005,.0001],other_friction)
    np.testing.assert_array_equal(new_friction,[coeff[0],coeff[0],coeff[1],coeff[2],coeff[2]])
