# MuJoCo user examples

Use Linux x86_64, Python 3.10/3.11 and the fork wheel installed by `[mujoco]`.
Install `[build,mujoco]` when generating resources. The fork Release fixes the
MuJoCo 3.16.0 mesh SDF sign error pending upstream PR #3689.

```sh
python -m xbox_gamepad_physics build-resources --backend mujoco \
  --archive ./xbox_gamepad_physics-resources-0.4.1.zip \
  --resources ./gamepad_resources --offline
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
```

## Load and drive by name

```python
from xbox_gamepad_physics import GamepadState
from xbox_gamepad_physics.mujoco import load_standalone

scene = load_standalone(fixed_root=True)
pad = scene.gamepad
pad.set_gamepad_targets(GamepadState.xbox_one_s({'south': .65}))
scene.step(100)
print(pad.joint_positions())
print(pad.gamepad_state().channel('south'))
```

The caller owns stepping. Select fixed/free root before compilation; use
`attach_to_spec` to compose a caller-owned model. The action value above is a
software demonstration, not physical calibration.

## Render a reference image

`render_reference.py` renders the native geometry using a caller-supplied camera
plan. Run from the checkout with the package installed:

```sh
python examples/mujoco/render_reference.py --resource-root ./gamepad_resources \
  --camera-plan /path/to/camera_plan.json --output ./reference_images
```

The classic renderer approximates source PBR materials. Rendering and signal
readout do not establish contact qualification. See [backend usage](../../docs/mujoco_backend.md)
for the known Pair failure, transient limit overshoot and non-real-time cost.
