"""Historical MuJoCo API. Imports remain lazy; loading reports that
MuJoCo is outside the v0.3.0 release scope. Frozen resources remain in Git only.
"""

from .attach import CompiledAttachment, GamepadAttachment, attach_to_spec
from .handle import MujocoGamepadHandle
from .loader import LoadedScene, load_scene
from .visual import (
    LoadedVisualScene,
    VisualAttachment,
    attach_visual_to_spec,
    load_visual_scene,
)

__all__ = [
    "CompiledAttachment",
    "GamepadAttachment",
    "LoadedScene",
    "MujocoGamepadHandle",
    "attach_to_spec",
    "load_scene",
    "LoadedVisualScene",
    "VisualAttachment",
    "attach_visual_to_spec",
    "load_visual_scene",
]
