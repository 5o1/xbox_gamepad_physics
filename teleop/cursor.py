"""Camera-plane cursor conversion to the unchanged world-coordinate Command."""
import math
from .session import quat_multiply, rotation_quaternion
from .views import camera_basis, project


def mouse_translation(view, pixels, gain_mm_per_pixel):
    right, up, _ = camera_basis(view)
    dx, dy = pixels
    return tuple((dx*r-dy*u)*gain_mm_per_pixel/1000 for r,u in zip(right,up))


def rotate_vector(q, vector):
    return quat_multiply(quat_multiply(q,(0,*vector)),(q[0],-q[1],-q[2],-q[3]))[1:]


def front_point(pose, reference):
    return tuple(p+v for p,v in zip(pose[:3],rotate_vector(pose[3:],reference)))


def key_rotation(view, keys, pose, degrees, reference):
    """Choose signs by the projected front; both axes pass through the root.

    At a geometric extremum/parallel axis the tip cannot move in the requested
    direction. Keep the specified axis; do not introduce an automatic roll axis.
    """
    right, up, _ = camera_basis(view)
    result = [0.,0.,0.]
    for positive,negative,axis,image_axis in (("KeyW","KeyS",right,1),("KeyA","KeyD",up,0)):
        if positive not in keys and negative not in keys:
            continue
        candidates=[]
        for sign in (1,-1):
            delta=rotation_quaternion([sign*x*math.radians(degrees) for x in axis])
            q=quat_multiply(delta,pose[3:])
            candidates.append(project(view,front_point([*pose[:3],*q],reference))[image_axis])
        sign=1 if candidates[0]<=candidates[1] else -1
        amount=sign*(int(positive in keys)-int(negative in keys))
        result=[v+amount*a for v,a in zip(result,axis)]
    return tuple(result)


def depth_translation(view, keys):
    _,_,forward=camera_basis(view)
    amount=int("KeyE" in keys)-int("KeyQ" in keys)
    return tuple(amount*f for f in forward)
