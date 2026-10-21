# MuJoCo inspection and acceptance

The contact and native readback tools are checkout-only under `tests/acceptance/`;
they are not installed by the wheel. Run these scripts from the checkout root
with that directory on the Python search path (the runtime can remain installed):

```sh
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
```

Use the generated `mujoco/full_controls` resources and the public loaders.
`acceptance.py` runs the frozen contact suite; `render_contact_replay.py`
replays recorded motion without running new physics. `render_reference.py`
uses the shared comparison camera plan for appearance review.

## Review with the existing gamepad overlay

After generating the contact videos, export the actual canonical states using
the identical video sample selection, build the page, and serve it locally:

```sh
PYTHONPATH=src python examples/mujoco/export_overlay.py \
  --traces /path/to/press_results --directory /path/to/review
python examples/mujoco/build_review.py \
  --directory /path/to/review --results /path/to/press_results/results.json
PYTHONPATH=src python examples/mujoco/serve_review.py \
  --directory /path/to/review --port 8774
```

Open `http://127.0.0.1:8774/traces/index.html`. The page reuses the installed
`gamepad_overlay` SVG renderer and canonical adapter. Video frame timestamps
select the recorded 32-value state, availability/task masks and device metadata;
there is no second signal mapping. Pair is displayed separately. Seeking,
changing cases and selecting slow clips update the same overlay.

The server binds only to loopback and uses the existing overlay service's
explicit review-directory mount. Close it with Ctrl+C. Directly opening the
HTML file plays the videos but cannot load the ES-module overlay.

New `MujocoPressExecutor.sample()` records include the complete canonical-frame
identity. For a live handle, `gamepad.gamepad_state()` returns the same public
`GamepadState` used by this adapter. The viewer does not control physics.
