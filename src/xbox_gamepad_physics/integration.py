"""Integration instructions and read-only environment diagnostics."""

from importlib import metadata
import platform
import re

from .errors import XboxGamepadPhysicsError
from .resources import resource_status


GUIDE = """Xbox One S integration guide

1. Environment and installation
   Supported: Linux x86_64 + NVIDIA, Python 3.10, RoboTwin fork / SAPIEN 3.0.3.
   SDF requires SAPIEN 3.0.3. Install the Release wheel with [build,robotwin]:
     python3.10 -m pip install './xbox_gamepad_physics-VERSION-py3-none-any.whl[build,robotwin]'
     xbox-gamepad-physics build-resources --archive INPUT.zip --resources ./gamepad_resources --offline
   Set XBOX_GAMEPAD_PHYSICS_RESOURCES to the prepared directory.
   Run xbox-gamepad-physics doctor to inspect versions, resources and extras.

2. Load into your existing scene
   from xbox_gamepad_physics.robotwin import load_into_scene
   gamepad = load_into_scene(scene, pose=[0, 0, 0.8, 1, 0, 0, 0], fixed_root=True)
   print(gamepad.gamepad_state().channel('left_x'))
   For a new standalone scene use the public robotwin.create_scene().
   Do not import internal examples modules. Export runnable examples with:
     xbox-gamepad-physics example export ./gamepad_example

3. Interaction
   Read gamepad_state(); set_gamepad_state(state) writes joint positions;
   set_gamepad_targets(state) writes drives, followed by your scene.step().
   Adapt by channel name, never tensor index. Pair is a separate physical event.
   Channel names follow SDL3 (by position, not by Xbox label):
     A south, B east, X west, Y north, View back, Xbox guide, Menu start,
     LB left_shoulder, RB right_shoulder, LT left_trigger, RT right_trigger,
     left stick tilt left_x/left_y, right stick tilt right_x/right_y,
     stick clicks left_stick/right_stick, D-pad dpad_up/down/left/right.
   Sticks range -1..1; triggers and buttons range 0..1.
   Example: GamepadState.xbox_one_s({'south': 1.0, 'left_x': 0.8})
   Your scene owns timestep, lights, cameras and object poses.

4. Rendering
   Default raster rendering supports the frozen materials and ABXY lettering.
   load_into_scene does not select shaders or change global render settings.
   Optional: robotwin.apply_review_rendering() reproduces the review RT settings.
   It changes SAPIEN GLOBAL camera shaders and other rendering settings, affecting
   ALL cameras in ALL scenes in the process. Use it only for review reproduction,
   before renderer/camera creation, never as a required integration step.

5. Common pitfalls
   Resource meshes and URDF are internal build artifacts. Direct loading omits
   appearance materials, SDF configuration and signal mapping.
   SDF cannot collide with add_ground planes or another SDF: use a static box.
   Internal collision filtering reserves groups[2] bit31 and groups[3]=0x5842;
   sharing these with external objects can suppress intended contacts.
   robotwin.diagnose_scene(scene) reports official loads, suspected raw imports,
   planes below SDF gamepads and the active global camera shader without edits.
   Successful loading/signals are separate from contact or dynamics validation.
"""


_EXTRAS = {
    "build": ("numpy", "trimesh", "Pillow", "manifold3d"),
    "robotwin": ("sapien",),
    "example": ("PyYAML", "numpy", "Pillow", "transforms3d"),
    "teleop": ("aiohttp", "PyYAML", "numpy", "Pillow", "transforms3d", "opencv-python", "trimesh", "manifold3d"),
    "maintainer": ("coacd",),
    "mujoco": ("mujoco",),
    "isaac": (),
}


def _version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def diagnose_environment(*, backends=("robotwin",)):
    """Inspect installed distributions and resource readiness without building."""
    python = platform.python_version()
    sapien = _version("sapien")
    mujoco = _version("mujoco")
    parsed = re.match(r"(\d+)\.(\d+)\.(\d+)", sapien or "")
    sdf = bool(parsed and tuple(map(int, parsed.groups())) >= (3, 0, 3))
    try:
        resources = resource_status(backends=backends)
        resources["ready"] = (not resources["missing"] and
                              not any(node["stale"] for node in resources["nodes"]))
    except (XboxGamepadPhysicsError, ImportError, OSError, ValueError) as error:
        resources = {"ready": False, "error": str(error)}
    extras = {}
    for extra, distributions in _EXTRAS.items():
        versions = {name: _version(name) for name in distributions}
        extras[extra] = {"installed": all(versions.values()), "distributions": versions}
    runtime_ready = all(sdf if name == "robotwin" else mujoco == "3.16.0" for name in backends)
    return {"backends": list(backends), "runtime_ready": runtime_ready,
            "mujoco": mujoco, "supported_mujoco": mujoco == "3.16.0",
            "python": python, "supported_python": python.startswith(("3.10.", "3.11.")),
            "python_support": {"core": ["3.10", "3.11"], "robotwin": ["3.10"], "mujoco": ["3.10", "3.11"],
                               "isaac": "External Python 3.11 platform; backend not implemented in C1"},
            "sapien": sapien, "supported_sapien": sapien == "3.0.3",
            "sdf_supported": sdf,
            "resources": resources, "extras": extras}


MUJOCO_GUIDE = """MuJoCo Xbox One S integration guide

1. Install with [build,mujoco] in Python 3.10 or 3.11 (MuJoCo 3.16.0):
     python -m pip install 'xbox-gamepad-physics[build,mujoco]'
     xbox-gamepad-physics build-resources --backend mujoco --archive INPUT.zip --resources ./gamepad_resources --offline
   Set XBOX_GAMEPAD_PHYSICS_RESOURCES to the prepared directory.
   Inspect with status --backend mujoco and doctor --backend mujoco.
   verify --backend mujoco reports the declared physical acceptance gate;
   available assets may remain blocked while contact acceptance is pending.

2. Let the caller compile its model, then bind by name:
   import mujoco
   from xbox_gamepad_physics.mujoco import attach_to_spec, load_standalone
   parent = mujoco.MjSpec.from_string('<mujoco/>')
   binding = attach_to_spec(parent, prefix='pad_', fixed_root=True)
   model = parent.compile()
   data = mujoco.MjData(model)
   pad = binding.bind(model, data)
   Choose fixed_root before compile. The fragment does not set global options.
   For standalone use: scene = load_standalone(fixed_root=True).

3. Read gamepad_state() and set_gamepad_targets(state) by channel name.
   The caller owns stepping: mujoco.mj_step(model, data). Pair remains separate.
   Binding checks named controls; pad.findings reports collision-bit overlap and material
   degradation. Classic Phong rendering approximates the upstream PBR material;
   successful loading and signals do not establish contact acceptance.
"""
