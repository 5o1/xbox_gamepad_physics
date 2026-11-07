# Native circular stick limits

The common contract requests a strict bound on the real shaft angle relative
to the controller, independently of click travel. The existing 23 degree value
is a simulation envelope, not a newly measured hardware dimension.

The backend now encodes the cone in MJCF using a native spatial-tendon length
limit. MuJoCo solves its reactions together with contacts and floating-root
dynamics. The former post-step position projection and velocity impulse have
been removed from stepping, position setters and reset.

## Ordinary native stepping

```python
import mujoco
from xbox_gamepad_physics.mujoco import load_standalone

scene = load_standalone(fixed_root=True)
mujoco.mj_step(scene.model, scene.data)
# Equivalently: scene.step() or scene.step(nstep=8).
```

Caller-owned models use the same native call. A handle list is unnecessary.
The generated XML includes these constraints. It needs no Python state repair.
The separate MjSpec-only SDF-depth setting still requires `make_spec`.

## Representation and parameters

Two invisible, massless sites are placed on the common reference and moving
shaft directions, each a distance L from their common pivot. Their separation
is `2*L*sin(shaft_angle/2)`. A native upper length bound of
`2*L*sin(max_angle/2)` therefore describes the circular cone exactly in geometry.
The frozen chain places the shell-fixed click slide before the two hinges.
The reference site is attached to the translated frame before the first hinge,
with the shell direction/pivot transformed into that frame. Both endpoints
therefore share click translation: tendon length and its click Jacobian remain
independent of click travel. No bodies, inertias or extra degrees of freedom are
introduced. Legacy tilt-first chains retain their shell reference site.

L=1 m is a mathematical unit-direction coordinate, not a hardware dimension or
an internal cable. There is no tendon spring, damping, friction or armature.
The owner selected the tested response on 2026-10-20:
`solreflimit=(0.000001 s, 5)`, `solimplimit=(0.9999, 0.9999, 0.001, 0.5, 2)`,
margin 0. `backend_options.mujoco.limit_response` records these numerical values
and their evidence; they are not hardware measurements. Standalone models and
the press executor use `discrete`, refsafe disabled, 0.0005 s physical steps,
Newton, 100 iterations, tolerance 1e-8 and diagexact disabled. The frozen 0.004 s
outer step still contains eight substeps. The selected no-contact experiment
reduced repeated rebound; its first crossing still exceeded the boundary by
about 0.35 degrees. This is not a bound for other loads or contact scenes.

The mapping report records the actual tendon response. To override, supply an
explicit calibration with `backend_options.mujoco.limit_response` and rebuild,
or edit the instance tendons before compile. Contact geom parameters and caller global options are
unchanged. Redundant individual tilt-hinge limits remain disabled; the coupled
native tendon now provides the cone limit. Click scalar limits remain enabled.
Attachment reports differences from the recommended timestep, integrator and
refsafe, but never applies those global options to a caller-owned model.

## Click threshold spring (approved 2026-11-07)

Both click joints use native passive springs with common stiffness 1000 N/m
and `springref=-0.0074 m`, producing `-(7.4 N + 1000 N/m*q)` at rest.
Common drive damping 2.8 N s/m and passive damping 0.14 N s/m are summed
once as joint damping 2.94 N s/m. Their return actuators and affine biases are
removed. Passive springs have no native actuator force clamp; the common
10.4 N drive effort limit is retained as metadata and explicitly unmapped.
Neither callback forces nor signal thresholds are added.

`backend_options.mujoco.click_limit_response` applies the owner-approved
stiff limit profile above to the two scalar click stops, with native joint
`margin=1e-8 m` (10 nm). Owner ruling 4 approved it on 2026-11-07,
using the interior of the passing 1-30 nm set summarized in
`docs/mujoco_backend.md`.
This is a numerical policy, not hardware physical data. The margin activates
the stop at q=0 on the first preloaded step and shifts its reference 10 nm
into the allowed range. Other scalar stops, tendon settings and
contact geoms are unchanged. Step size remains 0.0005 s, with eight physics
steps per 0.004 s outer tick. Startup theory and controls are recorded in
`docs/mujoco_backend.md`; loading and contact checks of a newly integrated
wheel remain separate from those historical native results.

For passive click joints `set_joint_target` changes `model.qpos_spring`, and
`restore_passive_targets`/default reset restore the common rest reference.
This model parameter is shared by all `MjData` instances using that compiled
model; separately prefixed attachments address distinct coordinates. It does
not alter the observed signal or write the click position.

## Accuracy and observation

Native limits are compliant and may penetrate their target boundary. This does
not meet the common exact hard-bound guarantee. The manifest declares strict
hard-limit support false and loading reports `strict_shaft_limit_unsupported`
as an error finding. That finding describes an unmet acceptance requirement;
it is not repaired by hiding the excess or changing the common contract.

On 2026-10-20, the owner provisionally accepted this limit item for MuJoCo M2:
the measured first crossing exceeded 23 degrees by about 0.353591 degrees,
settling to about 0.0000289 degrees excess under sustained load. This known
transient no longer blocks subsequent M2 acceptance work. The strict capability
and diagnostic remain unchanged; the decision is recorded in
`build/experiments/mb_m2/LIMIT_ACCEPTANCE.md`.

`handle.tilt_limit_state()` reports actual angles, requested maxima and excess.
Ordinary state reads remain available when the native solver returns an outside
state. Explicit outside position writes are rejected atomically, but neither
reset nor setters generate an additional velocity impulse. Native reaction loads
are included in `data.qfrc_constraint`; no separate added impulse exists.

Basis: MuJoCo 3.16.0 `doc/XMLreference.rst`, spatial tendon `limited`, `range`,
`solreflimit`, `solimplimit` and `margin`; `src/user/user_init.c`,
`mjs_defaultTendon`; and the common shaft-pivot/axis definition.
