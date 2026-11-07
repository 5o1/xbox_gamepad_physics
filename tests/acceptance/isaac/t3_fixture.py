"""Ruling-1 hybrid sphere fixture: horizontal positioning, constant normal force.

The initial cooked-SDF normal supplies a horizontal preload against the sloped
upper edge. There is no position feedback or support along the shell normal.
All gains and force bounds belong to the frozen probe fixture, not the gamepad.
"""
import math


def sphere_force(target, position, velocity, inward, surface_normal, *, normal_force,
                 mass, gravity, stiffness, damping, horizontal_force_limit):
    dot=lambda a,b:sum(x*y for x,y in zip(a,b))
    outward=tuple(-v for v in inward)
    support=dot(surface_normal,outward)
    if support<=0:raise ValueError('upper-edge fixture requires an upward supporting surface normal')
    raw=tuple(stiffness*(t-p)-damping*v for t,p,v in zip(target,position,velocity))
    horizontal=tuple(r-dot(raw,inward)*n-normal_force*(g-support*u)/support
                     for r,n,g,u in zip(raw,inward,surface_normal,outward))
    length=math.sqrt(dot(horizontal,horizontal));scale=min(1.,horizontal_force_limit/length) if length else 1.
    return tuple(scale*h+normal_force*n-mass*g for h,n,g in zip(horizontal,inward,gravity))
