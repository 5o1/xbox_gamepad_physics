# RoboTwin diagnostics and probes

These tools run only from a source checkout with the relevant SAPIEN/RoboTwin
prerequisites. They are excluded from the wheel.

- `robotwin_gamepad_asset_probe.py`: minimal native task used by
  `scripts/validate_robotwin_task_integration.py` for lifecycle investigation.
- `robotwin_left_stick.py`: left-stick return/contact probe and optional
  diagnostic renders. Its fixture parameters are experimental settings.

User loading, named drives and visual inspection are documented in
[examples/robotwin](../../examples/robotwin/README.md). Frozen press execution and
scoring live under `tests/acceptance/robotwin/`; these one-off probes do not
replace that suite.
