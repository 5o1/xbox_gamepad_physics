# Frozen MuJoCo contact acceptance

Run from the checkout root with the runtime package and build/MuJoCo dependencies
available. This tool is excluded from the wheel.

```sh
python -m tests.acceptance.mujoco.run_suite \
  --resource-root ./gamepad_resources --output ./build/contact_results
```

Use `--case NAME` repeatedly for a subset. Unrun cases retain their denominator
and remain explicitly unrun. The command uses the unchanged frozen
`ruling20_sdf303_v1` data, executor and scoring; it is separate from a user
loading example. Archived-result render/overlay tools are in
[experiments/mujoco](../../../experiments/mujoco/README.md).
