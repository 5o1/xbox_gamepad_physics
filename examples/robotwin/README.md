# RoboTwin/SAPIEN user examples

Install the wheel with `[build,robotwin,example]`, import its input zip, and set
`XBOX_GAMEPAD_PHYSICS_RESOURCES`. Use SAPIEN 3.0.3 for the default SDF collision.

## Export a standalone example

```sh
xbox-gamepad-physics example export ./gamepad_example
```

The exported directory contains `run_robotwin.py`, `smoke_full_controls.yaml`
and `render_review.yaml`. The checkout's [run_robotwin.py](../../run_robotwin.py)
uses the same packaged entry point. The caller supplies any RoboTwin asset root.
See [integration instructions](../../docs/robotwin_backend.md) for task lifecycle
and configuration details.

## Load into an existing task

```python
from xbox_gamepad_physics import GamepadState
from xbox_gamepad_physics.robotwin import load_into_scene

pad = load_into_scene(task.scene, pose=mount_pose, fixed_root=True)
pad.set_gamepad_targets(GamepadState.xbox_one_s({'south': .65}))
# Advance the caller's scene, then read named signals.
print(pad.gamepad_state().channel('south'))
```

Choose the mount pose for your own scene. Use a static box as SDF support;
`add_ground` planes do not support SDF contacts. The loader retains the caller's
lights and cameras. Named drive targets take effect during subsequent steps.

## Inspect appearance

[robotwin_visual.py](../robotwin_visual.py) loads the visual model, can save
images and can open SAPIEN's native viewer with `--interactive`. This visual-only
example does not create contact dynamics.

[The MuBlE visual example](../muble_visual.py) applies a caller-supplied pose trace
inside the approved Blender scene. Loading, rendering and signal readout do not
establish contact qualification or hardware calibration.
