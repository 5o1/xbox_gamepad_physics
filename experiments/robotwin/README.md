# RoboTwin checkout diagnostics

Reusable frozen execution/scoring stays in `tests/acceptance/robotwin`. One-off mechanism probes, compatibility searches, stress diagnostics and review plotting live here. They are maintenance tools, not runtime hooks or hardware identification. Use explicit historical resource snapshots when replaying a historical diagnosis; the v0.4.2 default has changed.

`joint_readback.policy()` is the single readback helper used by the factor, force-law and tilt/preload diagnostics. The factor, anchor and overdrive diagnostics moved from acceptance during v0.4.2 cleanup. Their original bytes and old/new path mapping are retained in the release-work backup, so old reports continue to identify the paths actually run at the time.

Run scripts as modules from the checkout with the appropriate simulator/build dependencies, for example `python -m experiments.robotwin.stick_click_factors --help`. Supply resource/output paths explicitly. No GUI, hardware IO or training is needed. Large traces, local screenshots, fetched SDK source dumps and prototype execution directories are historical checkout evidence and are excluded from the public release allowlist.

The authoritative current defaults and bounded validation summary are in `references/robotwin_v042_policy.json` and `docs/reports/v0.4.2/robotwin.md`. Diagnostic0.002Nm and tanh curves were not adopted. These scripts do not change frozen acceptance criteria or select parameters from T1-T4 pass/fail results.
