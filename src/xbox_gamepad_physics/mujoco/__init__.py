"""MuJoCo integration for the Xbox One S physical asset.

Importing this package is safe without MuJoCo installed. Runtime calls fail
with a project-specific dependency error until the optional backend is present,
and with a readiness error while physical MJCF/MJZ resources remain ungenerated.
"""

from .attach import CompiledAttachment, GamepadAttachment, attach_to_spec
from .handle import MujocoGamepadHandle
from .loader import LoadedScene, load_scene

__all__ = [
    "CompiledAttachment",
    "GamepadAttachment",
    "LoadedScene",
    "MujocoGamepadHandle",
    "attach_to_spec",
    "load_scene",
]
