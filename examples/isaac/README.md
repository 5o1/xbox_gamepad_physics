# Isaac B1 review

Use the existing external G20 stack: Python 3.11, Isaac Lab 2.3.2, Isaac Sim 5.1
and its torch build. These dependencies are not installed by this repository.
The caller starts AppLauncher before importing pxr or Isaac native modules.

`build_usd` takes prepared common motion, physical, appearance and collision
descriptions. Appearance must already be bound to the common motion chain.
The B1 review accepts an explicit `--binding` JSON; the shared appearance-binding
patch is owned by the main integration session. No production code reads the
RoboTwin resource tree.

```bash
export LD_LIBRARY_PATH="<G20_ENV>/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$PWD/src"
<G20_ENV>/bin/python examples/isaac/review_b1.py \
  --resources <COMMON_RESOURCE_ROOT> --binding <COMMON_VISUAL_BINDING_JSON> \
  --output <REVIEW_OUTPUT> --root-mode fixed --headless --device cuda:0
```

Run `--root-mode free` in a separate application process. For the two visual
reviews add `--enable_cameras --render-mode RaytracedLighting` or
`--render-mode PathTracing`, plus `--camera-plan <D2_CAMERA_JSON>` and
`--hdr <APPROVED_BOILER_ROOM_HDR>`. The experiment launcher under
`build/experiments/mb_i2/run_remote.sh` isolates the target machine's Kit and
cache directories. Images use D2 full and ABXY cameras and the B1b render policy.

Create the caller's `Articulation` with `make_articulation_cfg`. After the
caller's reset initializes it, call `bind_articulation`. Target writes update
Isaac Lab buffers; the caller calls `write_data_to_sim`, steps the simulation,
and calls `update`. State synchronization writes joint state without stepping.
Reset restores passive targets by default. Root mode is fixed at USD creation;
there is no runtime root switch. The B1 scalar binding accepts one instance;
CUDA batching belongs to B2.

The USD contains explicit mass, COM, principal inertia, limits, force drives and
separate native viscous friction. Angular conversion occurs at the USD boundary
only; Isaac Lab actuator configuration receives the original SI parameters.
Each frozen CoACD object remains an individual convex shape. SDF is optional
and requires explicit cook settings; its default/contact gate has not run.

The four ABXY BLEND domes alone disable shadow casting, following B1b's actual
no-shadow control. Their opacity is constant linear coverage 64/255. OPAQUE
letter geometry remains visible. PreviewSurface's metallic workflow does not
fully implement glTF KHR dielectric specular F0 semantics.

B1 validates authoring, loading and appearance review. It does not establish
contact readiness, the 26-case pressing regression, CUDA mapping or throughput.

## Ruling 2 diagnostics and comparison

`check_collision_b3.py --collision sdf --spacing-mm .5 --cases Guide
--comparison-only --measure-guide-clearance` reproduces the Guide baseline.
The following switches change only the named diagnostic condition:

- `--shell-spacing-mm 1` or `2`: shell and front plate spacing only.
- `--shell-coacd`: frozen CoACD on the shell components only.
- `--shell-coacd --guide-coacd`: shell plus Guide use frozen CoACD.
- `--contact-offset-mm .1`: explicit contact-offset control on both controller and probe.
- `--guide-coacd`: supplementary Guide-only representation control.
- `--diagnostic-no-shell-contact`: supplementary sphere/shell pair isolation;
  allowed only with `--comparison-only`, never an acceptance configuration.

`--full-suite --comparison-only --case-start START --case-count COUNT` runs
bounded chunks of the same frozen suite. Physical failures are recorded and do
not stop a comparison chunk. Execution completion is distinct from physics pass.
The main assistant combined starts 0/6/12/18/24 with counts 6/6/6/6/2 for all 26.

`benchmark_b4.py` requires `--collision`, `--num-envs`, and a pre-launch
`--external-snapshot` file in addition to prepared resources/output. It uses
20 warm-up and 100 measured steps, no cameras, and one fixed controller per
environment. Native force-load times parsing plus cooking; initial reset and
repeated state reset have separate windows. An isolated cook-only duration is
unavailable and remains null. Total sampled GPU usage and torch allocations are
reported separately. These short measurements do not establish contact readiness.

The native batch adapter requires the cumulative common-layer patch described
in `build/experiments/mb_i2/SHARED_CHANGES.md`; it remains separate for integration.
No diagnostic candidate updates the default collision policy or physical model.
