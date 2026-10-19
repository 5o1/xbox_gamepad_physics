"""Bind common mechanical values to the native Isaac cone topology."""
from __future__ import annotations

import math

from ..backends.common.transforms import multiply, rotate


# Owner-requested inward compensation for native solver residuals, not a larger
# acceptance tolerance. The common shaft envelope and signal mapping stay intact.
# Evidence: build/experiments/mb_i2/native_cone_margin_20261020/REPORT.md.
NATIVE_CONE_ANGLE_SCALE = .998


def joint_chain(motion, limit):
    """Return the ancestor chain, excluding the independent click joint."""
    incoming = {joint.child: joint for joint in motion.joints}
    chain = []
    link = limit.moving_link
    while link != limit.reference_link:
        if link not in incoming or len(chain) >= len(motion.joints):
            raise NotImplementedError(f'{limit.name}: reference must be an ancestor of moving link')
        joint = incoming[link]
        chain.append(joint)
        link = joint.parent
    chain.reverse()
    # A spherical loop is redundant in translation only for concurrent hinges.
    # Adding it to another topology would change the public mechanism.
    if not chain or any(j.kind != 'revolute' for j in chain) or any(
            any(x != 0. for x in j.origin) for j in chain[1:]):
        raise NotImplementedError(f'{limit.name}: native cone needs concurrent revolute hinges')
    return tuple(chain)


def require_supported_constraints(motion):
    """Parse required shared values; unsupported mechanisms fail before spawn."""
    records = [r for r in motion.joint_space_constraints if r.get('enforcement') == 'hard']
    if not records:
        return ()
    from ..backends.common.constraints import ShaftTiltLimit
    limits = []
    for record in records:
        if record.get('type') != 'shaft_tilt_limit':
            raise NotImplementedError(f"Isaac does not implement hard constraint {record.get('id')}")
        limit = ShaftTiltLimit.from_record(record)
        joint_chain(motion, limit)
        limits.append(limit)
    if len(limits) > 2 or len({limit.name for limit in limits}) != len(limits):
        raise NotImplementedError('Isaac supports the two distinct gamepad shaft cones')
    return tuple(limits)


def validate_initial_positions(motion, physical):
    """Check the physical initial pose before constructing native objects."""
    for limit in require_supported_constraints(motion):
        orientation = (1., 0., 0., 0.)
        for joint in joint_chain(motion, limit):
            value = physical.return_laws[joint.name].initial_position.value
            if value is None:
                raise ValueError(f'{joint.name}: initial position needs evidence')
            half = .5*value
            norm = math.sqrt(sum(x*x for x in joint.axis))
            rotation = (math.cos(half), *(math.sin(half)*x/norm for x in joint.axis))
            orientation = multiply(multiply(orientation, joint.origin_orientation_wxyz), rotation)
        moving = rotate(orientation, limit.moving_axis)
        dot = sum(a*b for a, b in zip(limit.reference_axis, moving))
        if math.acos(max(-1., min(1., dot))) > limit.maximum_rad:
            raise ValueError(f'{limit.name}: initial position violates the hard shaft cone')


def verify_native_cones(articulation, motion):
    """Reject a legacy/preloaded articulation that lacks native cone reactions."""
    limits = require_supported_constraints(motion)
    if not limits:
        return
    from isaaclab import sim as sim_utils
    from pxr import UsdPhysics, Tf
    from .builder import _axis_quaternion
    for root in sim_utils.find_matching_prims(articulation.cfg.prim_path):
        path = str(root.GetPath())
        for limit in limits:
            native = UsdPhysics.SphericalJoint(root.GetStage().GetPrimAtPath(
                path+'/ShaftLimits/'+Tf.MakeValidIdentifier(limit.name)))
            if not native or not native.GetExcludeFromArticulationAttr().Get() or not native.GetJointEnabledAttr().Get():
                raise ValueError(f'{limit.name}: preloaded asset lacks the required regular native cone')
            if native.GetAxisAttr().Get() != 'X' or any(not math.isclose(attribute.Get(),
                    math.degrees(limit.maximum_rad)*NATIVE_CONE_ANGLE_SCALE, rel_tol=0., abs_tol=1e-6) for attribute in (
                    native.GetConeAngle0LimitAttr(), native.GetConeAngle1LimitAttr())):
                raise ValueError(f'{limit.name}: native cone angle differs from the inward compensation policy')
            for actual, expected in ((native.GetLocalPos0Attr().Get(), joint_chain(motion, limit)[0].origin),
                                     (native.GetLocalPos1Attr().Get(), (0., 0., 0.))):
                if any(abs(a-b) > 8e-9 for a, b in zip(actual, expected)):
                    raise ValueError(f'{limit.name}: native cone pivot differs from common')
            for link, relation, axis, rotation in (
                    (limit.reference_link, native.GetBody0Rel(), limit.reference_axis, native.GetLocalRot0Attr()),
                    (limit.moving_link, native.GetBody1Rel(), limit.moving_axis, native.GetLocalRot1Attr())):
                if [str(p) for p in relation.GetTargets()] != [path+'/Links/'+Tf.MakeValidIdentifier(link)]:
                    raise ValueError(f'{limit.name}: native cone body binding differs from common')
                quat = rotation.Get()
                actual = (quat.GetReal(), *quat.GetImaginary())
                if any(abs(a-b) > 4e-7 for a, b in zip(actual, _axis_quaternion(axis))):
                    raise ValueError(f'{limit.name}: native cone axis differs from common')
