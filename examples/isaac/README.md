# Isaac preview user examples

Use an existing Python 3.11 environment with Isaac Lab 2.3.2, Isaac Sim 5.1 and
compatible torch. Install the supplied wheel in that environment; Isaac and
torch are external prerequisites, not installed by the `isaac` extra.

This directory contains loading, named-drive and signal-readout examples.
See [release notes](RELEASE_NOTES.md) and [known issues](KNOWN_ISSUES.md) for the
preview's limitations. Loading is separate from contact acceptance.

## Configure and launch

Merge [isaac_site.example.env](isaac_site.example.env) into your private site
file using the existing `xbox_gamepad_physics.teleop.site` settings format.
Keep filled settings in `configs/local/teleop_site.env` or another untracked
file. Use the base Isaac environment's library directory even when the selected
interpreter is a venv.

Provide the prepared resource tree containing `common/`, `usd/` and
`review_binding.json`, as described in [backend usage](../../docs/isaac_backend.md).
Keep relative USD/texture paths intact.

```sh
python examples/isaac/launch.py --site-config "$TELEOP_SITE_CONFIG" -- \
  --headless --device cuda:0 --root-mode fixed --drive-demo
python examples/isaac/launch.py --site-config "$TELEOP_SITE_CONFIG" -- \
  --headless --device cuda:0 --root-mode free --num-envs 64 --drive-demo
```

The launcher applies the selected interpreter, library path and GPU only to its
child process. A selected physical GPU is visible there as logical `cuda:0`.
It starts `load_and_read.py`, which also accepts explicit `--resources` and
`--output` arguments for a caller's existing launcher. Add `--build` to author
USD in the output directory. Use separate outputs when retaining multiple runs.

## Read and drive controls

`load_and_read.py` starts AppLauncher before importing native platform modules,
loads one articulation or a CUDA batch, drives A by the named `south` channel,
and reads canonical32 values, masks and the separate Pair event. The existing
zero-gravity demonstration uses its original timestep and actions; it does not
score a contact experiment or perform a native readback audit.

The example writes `preview_result.json` with installed versions, joint names,
initial/final signals and optional drive/batch observations. It records completed
execution without declaring physical qualification.

For a caller-owned scene, construct `make_articulation_cfg(...)`, initialize the
native articulation through the caller's reset, then call `bind_articulation` or
`bind_batched_articulation(..., env_origins=scene.env_origins)`. Read
`gamepad_state()` and set `set_gamepad_targets(state)` by channel name. The caller
owns reset, stepping, other actors and application lifetime.

Root mode is selected at USD creation. There is no runtime root switch.
`isaac.step(sim, gamepads=(handle,))` wraps native flush/step/update and does not
project state after solving. The preview retains the documented contact and
strict transient-limit limitations; use path tracing for clear ABXY images.
