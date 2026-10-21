# Historical MuJoCo code

These unchanged source snapshots document the former `resource_data/mujoco`
workflow. The `.py.txt` extension keeps them out of imports, test discovery and
the installed package. Their original resource and API assumptions are obsolete;
they are not supported commands for the current backend.

- `visual.py.txt`, `_manifest.py.txt`: the frozen visual API and old profile reader.
- `mujoco_*.py.txt`: former visual, signal and mocap-probe examples.
- `build_mujoco_full_controls.py.txt`, `export_mujoco_visual.py.txt`: former generators.
- `render_mujoco_*.py.txt`: former Filament review scripts.
- `test_mujoco_*.py.txt`: former tests of the historical resource tree.

Use `xbox_gamepad_physics.mujoco.load_standalone`, or `make_spec` / `attach_to_spec`
and `bind`, with the generated `mujoco/full_controls` artifact. Step with ordinary
`mujoco.mj_step(model, data)` or `LoadedScene.step()`.

Current inspection and acceptance scripts are in `examples/mujoco/`. The old
asset tree and experiment reports remain unchanged for provenance. See
`docs/full_controls.md` for current usage.
