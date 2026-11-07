# MuJoCo user examples

Use Linux x86_64, Python 3.10/3.11 and the fork wheel installed by `[mujoco]`.
Install `[build,mujoco]` when generating resources. The fork Release fixes the
MuJoCo 3.16.0 mesh SDF sign error pending upstream PR #3689.

```sh
python -m xbox_gamepad_physics build-resources --backend mujoco \
  --archive ./xbox_gamepad_physics-resources-0.4.2.zip \
  --resources ./gamepad_resources --offline
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
```

## Load and drive by name

```python
from xbox_gamepad_physics.mujoco import load_standalone

scene = load_standalone(fixed_root=True)
pad = scene.gamepad
lower, upper = pad.joint('a_press').range
pad.set_joint_target('a_press', lower + .65 * (upper - lower))
scene.step(100)
print(pad.joint_positions())
print(pad.gamepad_state().channel('south'))
```

The caller owns stepping. Select fixed/free root before compilation; use
`attach_to_spec` to compose a caller-owned model. The face-button target above is a
software demonstration, not physical calibration. A named target changes only
that joint, preserving passive click preload on the other controls.

## Load a passive stick click

Click joints have native passive springs and no `return_*_stick_click`
actuators. Apply an external load and let the engine move them:

```sh
python examples/mujoco/press_stick.py --resource-root ./gamepad_resources \
  --side left --force-n 8.14 --hold-s 0.5 --release-s 0.5
```

This standalone example uses native `mj_applyFT` at the moving stick COM, then
releases the force and prints measured travel and signal. The caller owns
stepping. It does not write click position, spring reference or a gamepad target.
It demonstrates downstream API use; it does not execute or score acceptance.

For passive clicks, `set_joint_target` writes the compiled model's spring
reference. Full `set_gamepad_targets` writes targets for every mapped control,
including neutral values for omitted channels, and can therefore override
click preload. Use external loads for physical pressing. Call
`restore_passive_targets()` to restore all common return targets when leaving
software target-drive mode. Spring references are shared by all `MjData`
instances using the same compiled model; separate attachments have separate
named coordinates.

## Render a reference image

`render_reference.py` renders the native geometry using a caller-supplied camera
plan. Run from the checkout with the package installed:

```sh
python examples/mujoco/render_reference.py --resource-root ./gamepad_resources \
  --camera-plan /path/to/camera_plan.json --output ./reference_images \
  --egl-device-id DEVICE
```

Choose a caller-owned EGL device, or omit the flag to retain the environment
selection. The classic renderer approximates source PBR materials. Rendering and signal
readout do not establish contact qualification. See [backend usage](../../docs/mujoco_backend.md)
for the known Pair failure, transient limit overshoot and non-real-time cost.
