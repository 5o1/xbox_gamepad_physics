"""Backend integration documentation; no environment self-test harness."""

GUIDE = """Xbox One S integration guide

1. Environment and installation
   Supported: Linux x86_64 + NVIDIA, Python 3.10, RoboTwin fork / SAPIEN 3.0.3.
   SDF requires SAPIEN 3.0.3. Install the Release wheel with [build,robotwin]:
     python3.10 -m pip install './xbox_gamepad_physics-VERSION-py3-none-any.whl[build,robotwin]'
     xbox-gamepad-physics build-resources --archive INPUT.zip --resources ./gamepad_resources --offline
   Set XBOX_GAMEPAD_PHYSICS_RESOURCES to the prepared directory.

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


MUJOCO_GUIDE = """MuJoCo Xbox One S integration guide

1. Install with [build,mujoco] in Python 3.10 or 3.11 (MuJoCo 3.16.0+concon.sdf3689.2):
     python -m pip install './xbox_gamepad_physics-VERSION-py3-none-any.whl[build,mujoco]'
   The extra selects the owner-maintained fork Release wheel for Python 3.10/3.11
   on Linux x86_64, including its SHA256. This corrects MuJoCo 3.16.0 mesh SDF
   sign errors with upstream PR #3689 (merged 2026-10-21); this release retains
   the tested fork:
     https://github.com/5o1/mujoco/releases/tag/v3.16.0-concon.sdf3689.2
     xbox-gamepad-physics build-resources --backend mujoco --archive INPUT.zip --resources ./gamepad_resources --offline
   Set XBOX_GAMEPAD_PHYSICS_RESOURCES to the prepared directory.
   Inspect generated paths with status --backend mujoco.

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


BACKEND_ENTRIES = """Xbox One S backend entrypoints

RoboTwin: xbox_gamepad_physics.robotwin.load_into_scene
  xbox-gamepad-physics guide --backend robotwin
  xbox-gamepad-physics build-resources --backend robotwin --archive INPUT.zip --offline
MuJoCo: xbox_gamepad_physics.mujoco.load_standalone / attach_to_spec
  xbox-gamepad-physics guide --backend mujoco
  xbox-gamepad-physics build-resources --backend mujoco --archive INPUT.zip --offline
Isaac (preview): xbox_gamepad_physics.isaac.build_usd / bind_articulation
  xbox-gamepad-physics guide --backend isaac
  build-resources --backend isaac requires a caller-owned AppLauncher process;
  it never starts Isaac automatically. See the dedicated native builder below.

The default instructions follow for RoboTwin.
"""

ISAAC_GUIDE = """Isaac Xbox One S preview integration guide

External prerequisites: Python 3.11, Isaac Lab 2.3.2, Isaac Sim 5.1 and compatible
torch. The [isaac] extra does not install or upgrade these platform packages.
Start AppLauncher before importing pxr or authoring USD.
Prepare common resources from the matching Release input zip, then build_usd
with root_mode="fixed" or "free". Construct cfg=make_articulation_cfg(...), then
native=cfg.class_type(cfg), or let InteractiveScene honor cfg.class_type.
After caller reset, bind_articulation; the caller owns flush/step/update.
The configured class initializes the persistent -7.4 N click effort. USD alone
contains a zero-target spring, not that runtime preload. A caller replacing
click effort targets must include the bias in new commands.
The generic build-resources --backend isaac does not launch the platform.
See docs/isaac_backend.md and examples/isaac for the direct authoring example.

Historical source-native validation: T1 6/6, T2 12/12, new-model point T3 v2 10/10,
and frozen SDF T4 23/26; Guide, Pair and R3 fail. These are not measurements of
the final integrated v0.4.2 wheel. Keep 4 ms/TGS, the historical 32/1 articulation
readback and 0.998 native cone margin. Strict transient/batch limits, contact
readiness, hardware calibration and RL remain unqualified. Use path tracing
for clearer ABXY; PreviewSurface is not full glTF specular equivalence.
"""


def diagnose_environment(*, backends=("robotwin",)):
    """Report installed versions and actual resource problems without loading engines."""
    from importlib import metadata
    import platform
    from .errors import XboxGamepadPhysicsError
    from .resources import resource_status
    extras = {
        'build': ('numpy', 'trimesh', 'Pillow', 'manifold3d'),
        'robotwin': ('sapien',), 'mujoco': ('mujoco',), 'isaac': (),
        'example': ('PyYAML', 'numpy', 'Pillow', 'transforms3d'),
        'teleop': ('aiohttp', 'PyYAML', 'numpy', 'Pillow', 'transforms3d', 'opencv-python', 'trimesh', 'manifold3d'),
        'maintainer': ('coacd',),
    }
    def version(name):
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None
    versions = {name: version(name) for name in ('sapien', 'mujoco', 'isaaclab', 'isaacsim', 'torch')}
    issues = []
    for backend in backends:
        dependency = {'robotwin': 'sapien', 'mujoco': 'mujoco', 'isaac': 'isaacsim'}[backend]
        installed = versions[dependency]
        if installed is None:
            issues.append(f'{dependency} is not installed')
        elif backend == 'mujoco' and installed != '3.16.0+concon.sdf3689.2':
            issues.append('MuJoCo requires the fork Release wheel selected by [mujoco]')
        elif backend == 'robotwin':
            import re
            parts = re.match(r'(\d+)\.(\d+)\.(\d+)', installed)
            if parts is None or tuple(map(int, parts.groups())) < (3, 0, 3):
                issues.append('SAPIEN SDF requires version 3.0.3 or newer')
    try:
        resources = resource_status(backends=backends)
        if resources['missing']:
            issues.append('Resources are missing; run xbox-gamepad-physics build-resources --archive INPUT.zip --offline')
        if any(node['stale'] for node in resources['nodes']):
            issues.append('Resources are stale; run xbox-gamepad-physics build-resources --archive INPUT.zip --offline')
    except (XboxGamepadPhysicsError, ImportError, OSError, ValueError) as error:
        resources = {'error': str(error)}
        issues.append(str(error))
    return {'python': platform.python_version(), 'backends': list(backends),
            'versions': versions, 'resources': resources,
            'extras': {name: {dep: version(dep) for dep in dependencies} for name, dependencies in extras.items()},
            'issues': issues}

GUIDE += """
SAPIEN GPU physics currently does not support stick-click preload.
Use CPU PhysX; GPU rendering is supported. CPU load_into_scene adds persistent
-7.4 N preload without initializing or stepping the caller's scene. The 10.4 N
cap applies only to the spring drive. Later set_qf overwrites remove preload;
compose caller loads with the existing qf. native_d6_cone full-controls defaults
require the approved sapien==3.0.3+concon.physx5.6.1.a3 port; the validated a2
build is also supported. Stock/a1 do not enable the required swing limits.
"""
