"""Camera presets and screen-to-world input basis, independent of SAPIEN."""
import math

# The fixed gamepad's button face lies in the world XY plane. World +Y is
# screen-up for its perpendicular front view; the camera looks along -Z.
VIEWS = {
    "front": ([0, 0, .43], [0, 0, .03], 38, [0, 1, 0]),
    "buttons_close": ([0, .015, .30], [0, .015, .03], 38, [0, 1, 0]),
    "overall": ([.46, -.46, .38], [.07, 0, .07], 45, [0, 0, 1]),
    "buttons": ([.01, -.01, .40], [0, 0, .03], 35, [0, 0, 1]),
    "left": ([-.30, -.18, .17], [0, 0, .04], 42, [0, 0, 1]),
    "right": ([.30, -.18, .17], [0, 0, .04], 42, [0, 0, 1]),
    # Historical visual-review cameras, relative to the gamepad root height.
    "reference_front": ([0, -.45, .05], [-.032, .15, -.25], 37, [0, 0, 1]),
    "reference_head": ([-.032, -.45, .55], [-.032, .15, -.25], 37, [0, 0, 1]),
    "triggers": ([0, .29, .18], [0, 0, .04], 38, [0, 0, 1]),
}
RENDER_CANDIDATES = {
    "raster": {"shader": "default", "samples_per_pixel": 4, "denoiser": "oidn"},
    "rt": {"shader": "rt", "samples_per_pixel": 1, "denoiser": "oidn"},
}


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def unit(v):
    length = math.sqrt(dot(v, v))
    return tuple(x/length for x in v)


def camera_basis(view):
    position, target, _, up_hint = VIEWS[view]
    forward = unit(tuple(t-p for p, t in zip(position, target)))
    right = unit(cross(forward, up_hint))
    up = cross(right, forward)
    return right, up, forward


def project(view, point):
    """Normalized image coordinates, x right, y down (used in input tests)."""
    position, _, fovy, _ = VIEWS[view]
    right, up, forward = camera_basis(view)
    offset = tuple(x-p for x, p in zip(point, position))
    depth = dot(offset, forward)
    scale = depth*math.tan(math.radians(fovy)/2)
    return dot(offset, right)/(scale*16/9), -dot(offset, up)/scale
