# Isaac preview acceptance tools

These checkout-only tools require an existing Isaac Lab 2.3.2 / Sim 5.1 / Python
3.11 / compatible torch environment. They are not runtime gates or wheel assets.
The caller selects the authorized device and isolates Kit/library/cache paths.
Native modules and USD authoring begin only after AppLauncher.

Prepare the matching common resource tree with the installed package. It must
contain `kinematics/xbox_one_s.json` and `common/xbox_one_s/{motion,physical,visual,collision}`.
The executor binds appearance from these standard inputs; no archived review
binding or prebuilt USD is required. It builds a fixed/free asset per run.

```bash
python -m tests.acceptance.isaac.stick_click \
  --resources "$ISAAC_RESOURCES" --output "$RUN/readback_fixed" \
  --protocol tests/acceptance/isaac/stick_click_protocol.json \
  --test readback --root-mode fixed --headless --device cuda:0
python -m tests.acceptance.isaac.stick_click \
  --resources "$ISAAC_RESOURCES" --output "$RUN/T3_point_left_8p14" \
  --protocol tests/acceptance/isaac/stick_click_t3_point_v2.json \
  --test T3P --side left --normal-force 8.14 --headless --device cuda:0
python -m tests.acceptance.isaac.stick_click \
  --resources "$ISAAC_RESOURCES" --output "$RUN/T4_A" \
  --protocol tests/acceptance/isaac/stick_click_protocol.json \
  --test T4 --case-id A --headless --device cuda:0
```

T1 uses `--side left|right --angle 0|12|20`; T2 uses
`--multiplier .5|.8|.95|1.1|1.3|1.6`. T3P uses both sides and
`--normal-force 1|2|4|6|8.14`. T4 reads all 26 original cases through the shared
tracked `tests/acceptance` runner and scores without changing thresholds.
Always inspect `result.json` (`status`, `passed`, `fixture_valid`, and import
provenance): Isaac application shutdown can return zero after a failed score.
A zero process exit code alone is not acceptance evidence.

`stick_click_protocol.json` is a byte-identical copy of the original shared
registration (`stick_click_threshold_20261105_v1`, SHA256
`57e6152d0873729de785941ddb062050744c7a8ce4247975d6f202233d3aa2db`).
Its historical scope text is preserved; Isaac uses its own native implementation
and approved numerical policy. This is shared judgement data, not a copied
RoboTwin implementation. `stick_click_t3_point_v2.json` retains its separately
registered SHA256 `56309fabc7f077f0155eb0a2acfe8e7b000b4bceccd40ea0d6ffc4964a47d576`.

The old sphere `--test T3` is retained for historical reproduction and is
**fixture invalid**, not a current physics qualification. For an explicit old
model comparison, provide `--baseline-source` pointing to the original 73c8676
source snapshot and `--baseline-resources` to its generated common resources.
The old builder/cfg/binder retain their original native drive representation.

`data/source_native_20261107.json` is a versioned historical scalar summary:
T1 6/6, T2 12/12, new-model point T3 v2 10/10, T4 23/26 with Guide/Pair/R3 failing.
Old positive-control limitations, sphere invalidation, protocol/archive digests,
and unverified native boundaries are retained. It does not qualify a newly
integrated wheel. Run installed-wheel validation from a non-editable environment
and check `package_file`, `package_version`, and `python_executable` in results;
do not put the checkout's `src` on PYTHONPATH during that validation.

One-off experiment launchers, plots and raw archives stay outside the component
commit.
