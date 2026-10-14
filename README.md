# Xbox One S Gamepad Physics

Xbox One S physical gamepad assets for RoboTwin/SAPIEN, with 20 active joints,
21 game input channels plus a separate Pair event, and a 32-dimensional canonical
state. The `full_controls` profile uses SDF collision meshes by default; CoACD
is available as an explicit option.

## Demo

Keyboard and mouse teleoperation of a floating gripper interacting with the
Xbox One S gamepad (v0.3.0, SDF + SAPIEN 3.0.3). Full Release video:
[`xbox_teleop_demo_v0.3.0.mp4`](https://github.com/5o1/xbox_gamepad_physics/releases/download/v0.3.0/xbox_teleop_demo_v0.3.0.mp4).

<!-- Inline player: drag the video below this line in the GitHub web editor -->

## Features

- Textured Xbox One S model with 2K PBR textures and articulated controls.
- Load into an existing RoboTwin task or SAPIEN scene with a caller-selected pose.
- Read signals and set joint positions or drive targets by name.
- Fix or release the root at runtime with CPU PhysX.
- Packaged examples, browser viewer, signal overlay, and local teleoperation.
- Offline resource import and local generation from approved inputs.

## Requirements

The v0.3.0 runtime targets Linux x86_64 with NVIDIA graphics, Python 3.10,
the [RoboTwin fork](https://github.com/5o1/RoboTwin), and SAPIEN 3.0.3.
Optional tools depend on the entry point:

| Feature | Additional requirements |
| --- | --- |
| Teleoperation | FFmpeg with working `h264_nvenc`, NVIDIA drivers/Vulkan, and a browser supporting H.264 WebCodecs and Pointer Lock; your own RoboTwin aloha-agilex gripper assets |
| Cycles viewer | Blender 4.5, supplied with `--blender` |
| Checkout npm entry points and JavaScript tests | Node 22 |

Node and Blender are not required for packaged local teleoperation. Python
extras install Python dependencies; external tools and RoboTwin assets must be
provided separately.

## Install

Download the wheel and resource zip from the
[v0.3.0 Release](https://github.com/5o1/xbox_gamepad_physics/releases/tag/v0.3.0).
The package is distributed through Release attachments rather than PyPI.

```sh
python3.10 -m pip install "./xbox_gamepad_physics-0.3.0-py3-none-any.whl[build,robotwin]"
python3.10 -m xbox_gamepad_physics build-resources \
  --archive ./xbox_gamepad_physics-resources-0.3.0.zip \
  --resources ./gamepad_resources --offline
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
python3.10 -m xbox_gamepad_physics verify --backend robotwin --profile full_controls
```

Add the `example` extra for exported examples or `teleop` for teleoperation,
for example `[build,robotwin,example,teleop]`. The repository is private:
automatic downloads fail without authentication. Download the attachments while
signed in, then import the zip with `--archive` as shown above.

The wheel builds runtime resources in your resource directory from the approved
input zip. Basic resource generation requires neither Blender nor a CoACD run.
`verify` checks resource readiness and required files; see
[resource import documentation](docs/importing.md) for details.

## Quick start

Add this method to your RoboTwin task, or merge its contents into your existing
`load_actors()`. Choose the root pose for your own scene; the example uses meters
and quaternion order `[qw, qx, qy, qz]`.

```python
from xbox_gamepad_physics import GamepadState, XBOX_ONE_S_CHANNELS
from xbox_gamepad_physics.robotwin import load_into_scene


def load_actors(self):
    self.gamepad = load_into_scene(
        self.scene,
        pose=[0.0, 0.0, 0.8, 1.0, 0.0, 0.0, 0.0],
        fixed_root=True,
        profile="full_controls",
        collision="sdf",  # Use "coacd" to select convex hulls.
    )
    state = self.gamepad.gamepad_state()
    print(state.channel("left_x"), state.channel("south"))
    target = GamepadState.from_mapping(
        {"left_x": 0.5, "south": 1.0},
        device_id=state.device_id,
        available_channels=XBOX_ONE_S_CHANNELS,
    )
    self.gamepad.set_gamepad_targets(target)
    self.gamepad.set_joint_target("left_stick_x", 0.0)
    self.gamepad.set_root_fixed(False)
```

Drive targets take effect during subsequent physics steps. For direct state
synchronization, `set_gamepad_state(target)` writes joint positions instead.
Call `set_root_fixed(bool)` only between completed physics steps; it supports
CPU PhysX, including GPU rendering, and rejects GPU/batched PhysX. Full
integration details are in [RoboTwin backend documentation](docs/robotwin_backend.md).

## Entry points

Examples export a runner and two configurations into a directory you choose:

```sh
xbox-gamepad-physics example export ./gamepad_example
python3.10 ./gamepad_example/run_robotwin.py ./gamepad_example/smoke_full_controls.yaml --resources ./gamepad_resources
python3.10 ./gamepad_example/run_robotwin.py ./gamepad_example/render_review.yaml --resources ./gamepad_resources --output ./review_output
```

Local teleoperation is the default. Supply your RoboTwin checkout and a new
session output directory; open the URL printed when the session is ready:

```sh
xbox-gamepad-physics teleop --robotwin-root /path/to/RoboTwin --gpu 0 --resources ./gamepad_resources --output ./teleop_session
```

`--gpu` selects an index in the caller-visible device list. Remote mode and
replay are described in [the teleoperation documentation](docs/importing.md).

Start the viewer or overlay with the installed commands:

```sh
xbox-gamepad-physics viewer --resources ./gamepad_resources --offline --blender /path/to/blender
xbox-gamepad-physics overlay
xbox-gamepad-physics overlay --trace-dir ./my_traces
```

The viewer is a kinematic inspector using the approved Blender/Cycles scene.
Without Blender, the page opens but Cycles rendering is unavailable. The overlay
prints a URL with a synthetic canonical demo trace. For your own trace, use the
printed address with `trace=/traces/<file>.json&autoplay=1`. See
[viewer documentation](viewer/README.md). From a checkout, the corresponding
entries are `npm run viewer -- --blender /path/to/blender` and
`npm run gamepad-overlay`.

## Signals and state

`GamepadState` uses `sdl3-gamepad-core-v1`: six SDL3 axes followed by 26 buttons,
with `available_mask`, `task_mask`, and `device_id`. Adapt by channel name rather
than array index. Unavailable channels are zero; `action_mask` is the intersection
of both masks. Xbox One S exposes 21 game channels; Pair is read separately with
`physical_events()` and written with `set_physical_events()`.

`GamepadSignalController` handles normalization, saturation, stick radial limits,
D-pad splitting, deadzones, and masks. The browser's 21-value W3C layout is a
boundary adapter. See [full controls](docs/full_controls.md) for the interface and
[project background](docs/project_background.md) for the detailed contracts.

## Known limitations

- Physical parameters remain estimates pending real-device calibration.
- Teleoperation still exhibits passive finger overspeed under external loads,
  inertia, and depenetration; diagnosis remains unresolved.
- Gripper contact with sticks can penetrate by approximately 2 mm.
- Freezing a tilted gamepad can produce stick signals of approximately 0.03.
- SDF does not collide with `add_ground` planes or another SDF object; use a
  static box for the supporting table.
- MuJoCo is outside the v0.3.0 release scope. Its frozen files are historical.

Loading and signal round trips do not establish contact-physics readiness or RL
results. See [release status and limitations](docs/plan.md) for the recorded scope.

## Documentation

The following documents are in Chinese:

- [Installation and resource import](docs/importing.md)
- [RoboTwin backend integration](docs/robotwin_backend.md)
- [Full controls and signal interface](docs/full_controls.md)
- [Pending visual review and measurements](docs/pending_user_review.md)
- [Release status and plans](docs/plan.md)
- [Collision optimization](docs/collision_optimization.md)
- [Project background, evidence, and maintenance history](docs/project_background.md)

## Development

Install from a checkout with the build extra, then run the local regression:

```sh
python3.10 -m pip install -e ".[build]"
python3.10 scripts/run_regression.py fast
```

Node 22 is needed for the JavaScript portion. Tests requiring optional dependencies
report skips. Existing setuptools 59 environments can use `--no-build-isolation`;
maintainer resource and evidence workflows are documented in
[project background](docs/project_background.md).

## License and attribution

Project code is [MIT licensed](LICENSE). The Xbox One S model is
[BatonyRobson's Xbox One S Controller/Gamepad (Animated)](https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4),
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The packed Boiler Room HDR by Oliksiy Yakovlyev / Poly Haven is CC0.
The gamepad-overlay renderer is Unlicense; Three.js is MIT.
See [third-party notices](THIRD_PARTY_NOTICES.md) and
[Three.js license](src/xbox_gamepad_physics/web/static/vendor/three/LICENSE).
