# Isaac diagnostics, probes and archived reviews

These are checkout-only experiments, not user loading examples or wheel contents.
For the loading and named-drive examples see [examples/isaac](../../examples/isaac/README.md).

## Diagnostic tools

The tools below are maintainer workflows and may require archived inputs absent
from the preview resources. All resource/archive/output paths are supplied by
the caller. The historical ruling-3 field scripts now require `--inputs`; the
SAPIEN bridge reads its optional library/include settings through the same private
site configuration. They do not change the preview defaults.

# Maintainer validation and historical diagnostics

Use the existing external G20 stack: Python 3.11, Isaac Lab 2.3.2, Isaac Sim 5.1
and its torch build. These dependencies are not installed by this repository.
The caller starts AppLauncher before importing pxr or Isaac native modules.

`build_usd` takes prepared common motion, physical, appearance and collision
descriptions. Appearance must already be bound to the common motion chain.
The native review accepts an explicit `--binding` JSON; the shared appearance-binding
patch is owned by the main integration session. No production code reads the
RoboTwin resource tree.

```bash
eval "$(python -m xbox_gamepad_physics.teleop.site --shell)"
export LD_LIBRARY_PATH="${TELEOP_ISAAC_LIBRARY_ROOT}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$TELEOP_ISAAC_PYTHON" experiments/isaac/review_b1.py \
  --resources "$TELEOP_RESOURCE_ROOT" --binding "$TELEOP_RESOURCE_ROOT/review_binding.json" \
  --output "$TELEOP_LOCAL_OUTPUT" --root-mode fixed --headless --device cuda:0
```

Run `--root-mode free` in a separate application process. For the two visual
reviews add `--enable_cameras --render-mode RaytracedLighting` or
`--render-mode PathTracing`, plus `--camera-plan "$TELEOP_CAMERA_PLAN"` and
`--hdr "$TELEOP_HDR"` from the private site configuration. The experiment launcher under
`build/experiments/mb_i2/run_remote.sh` isolates the target machine's Kit and
cache directories. Images use full-view and ABXY cameras and the transparent-dome shadow policy.

Create the caller's `Articulation` with `make_articulation_cfg`. After the
caller's reset initializes it, call `bind_articulation`.
`isaac.step(simulation, gamepads=(handle,))` is a convenience helper: it flushes gamepad
commands, advances one native physics tick and updates gamepad data. The same
native SDK calls can be used directly. The caller flushes/updates its other actors and sensors. State
synchronization writes joint state without stepping.
Reset restores passive targets by default. Root mode is fixed at USD creation;
there is no runtime root switch. The scalar binding accepts one instance;
Use bind_batched_articulation for CUDA batches.

The USD contains explicit mass, COM, principal inertia, limits, force drives and
separate native viscous friction. Angular conversion occurs at the USD boundary
only; Isaac Lab actuator configuration receives the original SI parameters.
SDF is the default collision policy under ruling 3, using the unchanged 0.5 mm
baseline cook settings. Full contact qualification remains pending. CoACD is an
explicit comparison option; each frozen object remains an individual convex shape.

The four ABXY BLEND domes alone disable shadow casting, following the reviewed
no-shadow control. Their opacity is constant linear coverage 64/255. OPAQUE
letter geometry remains visible. PreviewSurface's metallic workflow does not
fully implement glTF KHR dielectric specular F0 semantics.

The preview validates authoring, loading and appearance review. It does not establish
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

For an authorized continuation after a known scoring failure, use
`--full-suite --continue-on-regression --case-start START --case-count COUNT`.
This keeps the frozen scoring and records later failures while continuing.
A completed chunk with any physics failure reports `completed_with_failures`;
runtime and fixture errors still stop the process.

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

## Archived contact videos

`render_contact_replay.py --archive ARCHIVE --output OUTPUT --case Guide
--enable_cameras` renders recorded SDF states from the prepared continuation
archive. The caller launches the existing Isaac application with its normal
headless/device options. No physics steps or new scoring are performed.

Each video contains a full front view, a fixed contact close-up and a side view
of translucent source collision triangles. Playback is half-speed at 30 fps.
Green success or red failure titles reproduce the archived result. White-edged
red markers refer to shell contacts; green markers refer to moving parts.
The archived Isaac traces retain per-link aggregate contact positions, so these
markers do not represent every individual contact or a reconstructed SDF surface.

When an archived probe escapes the contact region, the camera keeps the controller
visible and labels the off-screen probe with its actual distance. Recorded probe
positions are never clamped or replaced.

To render an updated result generation, repeat `--result-dir DIRECTORY` for its
explicit directories beneath `ARCHIVE/output`, and set `--source-label Updated`.
The video manifest records this selection; duplicate cases across selected
directories are rejected. The original default selection reproduces the historical
pre-correction archive.

## Native shaft cone joints

The common motion contract's two hard `shaft_tilt_limit` records are parsed with
the shared `ShaftTiltLimit` value object. Apply the companion common-definition
patch and the existing shared CUDA mapper patch before native integration.

`build_usd` adds two regular spherical cone joints, excluded from the existing
20-coordinate articulation. Their equal half angles limit actual relative shaft
direction. They preserve click travel and supply native contact-coupled reactions.
Each stick keeps its two original hinges and independent click joint. The extra
spherical joint closes the loop between the controller body and the tilt frame.
The owner-selected inward numerical compensation multiplies the common maximum
by 0.998 when authoring both native cone half angles (23 degrees becomes 22.954
degrees). The common 23-degree envelope, hinge travel and signal mapping remain
unchanged. The USD sidecar records both the common and authored cone angles.
Rebuild older USD assets before binding; the binder checks the compensated value.
PhysX owns the dynamic constraint response together with contact and drive
response. The adapter does not request mass matrices, solve constraint impulses,
or rewrite positions or velocities after a native tick.

Configuration/binding validate initial state. Joint/reset writes validate the
complete candidate before any root or joint mutation. Values outside the actual
23-degree cone and outward boundary velocities raise `ValueError`. Validation
accounts for half-ULP coordinate representation and never modifies the supplied
state. This representation check is not a tolerance for dynamic solver error.
Binding a legacy asset lacking the required native cones also raises an error.

Use either the SDK lifecycle directly or the convenience helper:

```python
from xbox_gamepad_physics.isaac import step

probe.write_data_to_sim()             # caller-owned external actors
step(simulation, gamepads=(gamepad,), render=False, nstep=1)
probe.update(simulation.get_physics_dt())
```

The caller still owns application, scene, physics dt and reset. `nstep` repeats
native ticks without state projection. Raw SDK state writes bypass the handle's
input validation; native cone dynamics remain active with direct SDK stepping.

Native hard joints have finite solver residuals. Previous native load experiments
exceeded 23 degrees. The inward margin is checked against the unchanged 23-degree
upper bound after sustained loading; it is not a guarantee of zero transient
overshoot or support for arbitrary loads. No larger angular or velocity tolerance
has been adopted. Contact qualification and release readiness remain separate.

`check_shaft_limits.py --num-envs 1|64|1024 --root-mode fixed|free` checks actual
cones, state-write atomicity, native response and short interior/active costs.
It records inherited zero-violation checks separately from execution and stops
on a new fixture, finite-state or isolation failure. It requires the same
`--resources` and `--output` layout as the other examples. Historical videos use
the earlier common contract and do not validate the new native cone joints.

## Native cone load diagnostic

`probe_native_load.py --resources RESOURCES --source LEGACY_USD_DIRECTORY
--output OUTPUT --profile drive|ramp|step|pulse` measures the native spherical
cone without the Python shaft-limit adapter. The source directory contains
prepared `fixed.usda` and `free.usda` controller assets. Each torque and azimuth
gets an independent cloned environment with both root modes. External torques
are equal and opposite on the body and shaft; they bypass actuator effort caps.

`--tier low|high`, `--torques`, `--azimuths`, `--hold-s`, and
`--initial-angle-deg` select diagnostic inputs. `--without-cone` and
`--force-every-iteration` are explicit single-factor controls, not backend
defaults. Results include native link-axis angles, coordinate angles, anchor
error, loading phases and unloading recovery. A completed diagnostic can exceed
23 degrees and does not establish acceptance of the common hard-limit contract.
`--stick left|right`, `--drive-azimuths`, and `--drive-seconds` select the shaft,
drive directions and duration. `--cone-angle-scale` selects the diagnostic
native half-angle multiplier; 1.0 reproduces the historical unadjusted cone and
0.998 exercises the current inward compensation. The final 0.5 seconds of drive
or hold are summarized separately from the peak over the entire trajectory.

## Click diagnostics

`check_collision_b3.py --collision sdf --spacing-mm .5 --cases L3,R3
--comparison-only --diagnostic-stick-native-state` records native pre/post
velocities, COM/link states, projected joint forces and incoming joint wrenches.
The latter are total joint quantities, not isolated implicit-drive forces.
`--stick-coacd left|right` changes only that collision component. Optional
`--diagnostic-constant-hold-axis-force` freezes the final press force along the
press axis while retaining transverse PD positioning. The full-vector variant
also removes transverse positioning and can let the probe roll off.
`--diagnostic-lock-stick-tilt` adds temporary regular fixed constraints to the
tilt frames; it is a diagnostic intervention, not a delivered mechanism.
All these interventions require comparison-only mode and retain the frozen
scoring expression. Their scores do not constitute acceptance of a new policy.

`probe_click_axis_load.py` removes the probe and directly loads each click axis
with reference forces derived from the frozen spring law and probe force cap.
It preserves native passive drives, simulation settings and the original USD.

## Native cone replay videos

For newly executed contact cases, `render_contact_replay.py --orthographic`
uses synchronized front (+Z), top (+Y) and right (+X) orthographic cameras at
the same scale. `--overlay-dir` accepts frames captured from the existing
canonical32 SVG gamepad adapter. Their saved sample indices must match the
physical replay exactly. The footer shows recorded shaft angles. Replay uses
double-precision USD transforms, keeps the timeline stopped and preserves the
measured scores; it does not rerun contact physics.

`render_native_cone_replay.py --archive ARCHIVE --output OUTPUT --case DIRECTORY
--enable_cameras` displays a saved `check_shaft_limits.py` trajectory. Repeat
`--case` for additional directories beneath `ARCHIVE/output`. It uses native
Isaac RTX for synchronized orthographic front (+Z), top (+Y) and right (+X)
views of the same controller at the same sample and scale, with actual tilt and
the 23-degree envelopes. Default playback is 0.1x at 30 fps.

Only environment row zero was saved by that fixture. Free-root world poses
were not recorded, so the video explicitly uses the controller body frame.
The Kit timeline stays stopped. There are no new physics steps, interpolation,
angle clamping or acceptance scores; source failures remain visible. These
short drive clips do not replace the 26-case contact videos.
