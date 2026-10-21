# Isaac preview — 0.4.1

The prepared 0.4.1 package includes the Isaac adapter as a preview. User examples
load prepared resources, drive named controls and read signals; contact acceptance
and diagnostics are separate checkout tools.

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
- Named-drive and canonical signal-readout examples, using a caller-owned
  application and the existing private site configuration.

Release preparation also makes USD texture references relative and removes
machine-specific runtime paths from the adapter and diagnostic tools. The
launcher reuses the project's private site settings parser. Common-layer integration is part of the package. Acceptance execution, native
readback audits and diagnostic renders remain outside the wheel.

The latest frozen suite is **22/26**, including all eight stick directions.
Guide, Pair, L3 and R3 remain failed. L3/R3 diagnosis is recorded and parked.
See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) before using this preview for physics work.
