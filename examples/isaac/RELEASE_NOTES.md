# Isaac preview component for v0.4.2

This component consumes the click-first common chain, authors a zero-target
click spring, and initializes the constant native generalized preload through
the configured Isaac Lab asset class. USD alone does not carry that runtime
preload. Direct callers use `cfg.class_type(cfg)`; `InteractiveScene` uses the
configured class automatically. The application must exist before USD authoring.

The regular native spherical cone follows the click frame, preserving axial
travel while limiting shaft tilt. The approved 0.998 inward margin remains:
22.954-degree authored half-angles against the unchanged 23-degree common bound.
The component retains 4 ms/TGS and the historical 32/1 articulation readback;
it does not adopt another backend's solver policy.

Historical native source validation on 2026-11-07 recorded T1 6/6, T2 12/12,
new-model point-force T3 v2 10/10, and frozen SDF T4 23/26. The prior 22 passing
cases stayed passing and L3 improved; Guide, Pair and R3 remained failed. These
are source-worktree results, **not a test of the final integrated v0.4.2 wheel**.
The old model's point-force positive controls failed, so its zero low-load
signals are not evidence of correct physics. Sphere-based T3 fixtures were
invalidated and remain historical records.

The loading example builds from standard common resources and no longer needs
an archived `review_binding.json`. It records import provenance to help detect
an unintended source checkout during installed-wheel validation. Acceptance
execution and scores remain separate from user loading examples and the wheel.

See [known issues](KNOWN_ISSUES.md) and
[versioned source evidence](../../tests/acceptance/isaac/data/source_native_20261107.json).
The backend remains a preview; strict transient limits, full batch/scaling
qualification, contact readiness, hardware calibration and RL are not established.
