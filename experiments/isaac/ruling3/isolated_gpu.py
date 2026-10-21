"""Load the explicitly fetched PhysX GPU dependency from task scratch only."""
import ctypes
from pathlib import Path
import sapien.physx as physx
from xbox_gamepad_physics.teleop.site import require


def enable_gpu():
    if not physx.is_gpu_enabled():
        library = Path(require('TELEOP_PHYSX_GPU_LIBRARY'))
        ctypes.CDLL('libcuda.so', mode=ctypes.RTLD_GLOBAL)
        ctypes.CDLL(str(library), mode=ctypes.RTLD_LOCAL)
        physx._enable_gpu()
