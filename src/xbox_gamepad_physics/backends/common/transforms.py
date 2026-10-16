"""Small rigid-transform operations with explicit local-to-parent conventions."""
from __future__ import annotations
import math
from .model import Pose


def rotate(q, v):
    w, x, y, z = q
    a, b, c = v
    return ((1-2*(y*y+z*z))*a+2*(x*y-w*z)*b+2*(x*z+w*y)*c,
            2*(x*y+w*z)*a+(1-2*(x*x+z*z))*b+2*(y*z-w*x)*c,
            2*(x*z-w*y)*a+2*(y*z+w*x)*b+(1-2*(x*x+y*y))*c)


def multiply(a, b):
    w, x, y, z = a
    u, i, j, k = b
    return (w*u-x*i-y*j-z*k, w*i+x*u+y*k-z*j,
            w*j-x*k+y*u+z*i, w*k+x*j-y*i+z*u)


def compose(parent: Pose, local: Pose) -> Pose:
    offset = rotate(parent.orientation_wxyz, local.position_m)
    return Pose(tuple(a+b for a,b in zip(parent.position_m, offset)),
                multiply(parent.orientation_wxyz, local.orientation_wxyz))


def inverse(pose: Pose) -> Pose:
    w,x,y,z = pose.orientation_wxyz
    q = (w,-x,-y,-z)
    return Pose(rotate(q, tuple(-v for v in pose.position_m)), q)


def point(pose: Pose, value):
    return tuple(a+b for a,b in zip(rotate(pose.orientation_wxyz,value),pose.position_m))


def neutral_link_poses(motion):
    poses = {"controller_body": Pose()}
    pending = list(motion.joints)
    while pending:
        ready = [j for j in pending if j.parent in poses]
        if not ready:
            raise ValueError("motion joint chain is disconnected or cyclic")
        for joint in ready:
            poses[joint.child] = compose(poses[joint.parent], Pose(joint.origin, joint.origin_orientation_wxyz))
            pending.remove(joint)
    return poses
