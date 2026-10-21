# Isaac experimental preview — 0.4.0.dev20261020

This preview packages the implemented Isaac adapter and the frozen Xbox One S
resources for installation and review. The combined final v0.4.0 release remains
pending integration and complete acceptance of both backends.

Included capabilities:

- Direct pxr USD generation with explicit mass, principal inertia, joint limits,
  passive laws, native material bindings and individual frozen collision shapes.
- Fixed or free root selected at asset creation; caller-owned application,
  scene and stepping lifecycle.
- Scalar and CUDA batched handles, canonical32 values and masks, physical events,
  ordered subsets, partial reset and copy/borrow reads.
- Two regular native spherical cone constraints alongside the existing stick
  hinges; no post-step joint correction or custom mass-matrix solve.
- SDF 0.5 mm default under the owner's ruling; frozen CoACD comparison option.
- Latest 26-case comparison and true orthographic front/top/right replay videos
  with the existing SVG signal overlay, actual angles and pass/fail status.

Release preparation also makes USD texture references relative and removes
machine-specific runtime paths from the adapter and diagnostic tools. The
launcher reuses the project's private site settings parser. The accompanying
common-layer patches are applied to the preview wheel in isolated staging;
source integration remains a separate review step.

The latest frozen suite is **22/26**, including all eight stick directions.
Guide, Pair, L3 and R3 remain failed. L3/R3 diagnosis is recorded and parked.
See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) before using this preview for physics work.
