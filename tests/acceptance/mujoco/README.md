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

The stick-click protocol is frozen separately in `stick_click_protocol.json`
(`stick_click_threshold_20261105_v1`), copied without criterion changes from the
shared protocol. Run each gate explicitly, preserving the stop policy:

```sh
PYTHONPATH=src python -m tests.acceptance.mujoco.stick_click \
  --test K2b --resource-root ./gamepad_resources --output ./build/click/K2b
PYTHONPATH=src python -m tests.acceptance.mujoco.stick_click \
  --test T1 --resource-root ./gamepad_resources --output ./build/click/T1
```

`--test` also accepts T2, T3 and T4. T4 accepts `--historical-results PATH` for
the historical MuJoCo 25/26 archive; it stops at the first frozen or historical
baseline regression and retains all remaining rows as null. For a baseline-only
T3 run, `--baseline-comparison-only` records failures without requiring the old
model to pass. Each command archives the protocol and its SHA256. The runner
uses the asset's native numerical policy; it does not reduce the timestep.
T3 samples contact forces and raw travel at every native substep. Model
compilation is reused between compatible cases, with fresh MjData and native
fixture reset for each case.

For current point-force T3, retain the archived sphere protocol and use the
owner-approved `stick_click_t3_point_v2.json` with `point_v2.py`:

```sh
PYTHONPATH=src:. python -m tests.acceptance.mujoco.point_v2 \
  --resources ./gamepad_resources --output ./build/click/T3v2/new --label new
```

Use `--label old73c8676` and the unmodified historical resource root for the old
control. The v2 runner stops on an invalid fixture or a new-model physical gate
failure, retaining all ten planned rows; historical misclick failures are
reported without treating them as fixture failures. The v1 sphere runs are
archived as fixture-invalid, and are not a valid misclick comparison.

Ruling4 retains a 0.2s tilt-target ramp within the original one-second T1/T2
fixture settle. K2b uses the owner's explicit clarification: the first native
step and entire1s click minimum must be at least -4um, and every public signal
must remain exactly zero. Signed raw positions are always retained; numerical
nanometre penetration must not be hidden or confused with an exact hard bound.
