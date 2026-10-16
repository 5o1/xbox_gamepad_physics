"""Native MuJoCo backend with lazy optional dependency imports."""
from .attach import CompiledAttachment, GamepadAttachment, attach_to_spec, load_into_scene
from .handle import MujocoGamepadHandle
from .loader import GamepadSpec, LoadedScene, bind, load_scene, load_standalone, make_spec
from .diagnostics import diagnose
from .visual import LoadedVisualScene, VisualAttachment, attach_visual_to_spec, load_visual_scene

__all__ = ["CompiledAttachment", "GamepadAttachment", "GamepadSpec", "LoadedScene",
           "MujocoGamepadHandle", "attach_to_spec", "load_into_scene", "bind", "make_spec",
           "load_scene", "load_standalone", "diagnose", "LoadedVisualScene", "VisualAttachment",
           "attach_visual_to_spec", "load_visual_scene"]
