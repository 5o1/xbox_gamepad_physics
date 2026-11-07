"""The T3 probe must transmit its prescribed normal load without a guide."""
import math

import pytest

from tests.acceptance.isaac.t3_fixture import sphere_force


def dot(a, b):
    return sum(x*y for x,y in zip(a,b))


def unit(a):
    length=math.sqrt(dot(a,a))
    return tuple(x/length for x in a)


def add(a, b):
    return tuple(x+y for x,y in zip(a,b))


@pytest.mark.parametrize('inward', [(0.,0.,-1.), unit((1.,2.,-3.)), unit((-3.,1.,2.))])
@pytest.mark.parametrize('horizontal_limit', [.2, 16., 1e7])
def test_normal_load_is_preserved_under_large_position_error_and_saturation(inward, horizontal_limit):
    # Uneven surface and nonvertical shell: no world-Z shortcut is valid.
    seed=(.3,-.7,.2)
    tangent=unit(tuple(v-dot(seed,inward)*n for v,n in zip(seed,inward)))
    surface=tuple(-.8*n+.6*t for n,t in zip(inward,tangent))
    gravity=(0.,0.,-9.81); mass=.05; normal_force=6.
    force=sphere_force((100.,-70.,45.),(-.1,.2,.3),(.6,-.3,.8),inward,surface,
        normal_force=normal_force,mass=mass,gravity=gravity,
        stiffness=3000.,damping=12.,horizontal_force_limit=horizontal_limit)
    applied=add(force,tuple(mass*g for g in gravity))
    assert dot(applied,inward)==pytest.approx(normal_force,abs=2e-9)
    horizontal=tuple(f-normal_force*n for f,n in zip(applied,inward))
    assert math.sqrt(dot(horizontal,horizontal))<=horizontal_limit*(1+1e-12)
    if horizontal_limit<1e7:
        assert math.sqrt(dot(horizontal,horizontal))==pytest.approx(horizontal_limit)


def test_lateral_drift_is_restored_without_vertical_support():
    settings=dict(inward=(0.,0.,-1.),surface_normal=(0.,0.,1.),normal_force=1.,
                  mass=.05,gravity=(0.,0.,-9.81),stiffness=3000.,damping=12.,horizontal_force_limit=16.)
    force=sphere_force((0.,0.,0.),(0.,.001,-.2),(0.,0.,0.),**settings)
    assert force[1]==pytest.approx(-3.)
    # A 20 cm downward displacement must never produce an upward guide force.
    reference=sphere_force((0.,0.,0.),(0.,.001,0.),(0.,0.,0.),**settings)
    assert force==pytest.approx(reference)
    assert force[2]+.05*(-9.81)==pytest.approx(-1.)


def test_initial_horizontal_preload_balances_a_sloped_surface_reaction():
    normal_force=2.; mass=.05; gravity=(0.,0.,-9.81)
    surface=(-.6,0.,.8)
    force=sphere_force((0.,0.,0.),(0.,0.,0.),(0.,0.,0.),(0.,0.,-1.),surface,
        normal_force=normal_force,mass=mass,gravity=gravity,
        stiffness=3000.,damping=12.,horizontal_force_limit=16.)
    # A purely normal surface reaction of Fn/n_z balances the complete load.
    # This verifies the sign: the sphere pushes toward the cap, not away.
    reaction=tuple(normal_force/.8*v for v in surface)
    residual=tuple(f+mass*g+r for f,g,r in zip(force,gravity,reaction))
    assert residual==pytest.approx((0.,0.,0.),abs=1e-12)
    assert force[0]>0.
