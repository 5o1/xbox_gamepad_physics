# Experimental preview: known issues

The current asset is suitable for native loading, visual inspection, drive and
signal integration experiments. It has not passed complete contact acceptance
and is not the final v0.4.0 release. Failed scores retain the frozen thresholds.

| Area | Observed result | Delivery status |
| --- | --- | --- |
| Frozen 26-case SDF 0.5 mm suite | 22 pass; Guide, Pair, L3 and R3 fail; all eight stick directions pass | Publish the complete comparison and recorded videos |
| Guide | Regression against the passing SAPIEN baseline | Open; no fitted geometry or physical parameters adopted |
| Pair | Fails in both the current Isaac run and the SAPIEN baseline | Open; outside the canonical32 game tensor, exposed as a physical event |
| L3 / R3 | Persistent click-travel oscillation during contact; minimum hold signals 0.719 / 0.659 | Investigation parked by owner; no fix claimed |
| Native circular limit | Authored half-angle 22.954 degrees, from approved 0.998 compensation of the shared 23-degree limit | Tested steady loading stays below 23 degrees; strict transient guarantee is not established |
| Strict transient limit | A compensated free/N=64 sample reached 23.001294 degrees | Original strict per-substep gate remains failed |
| Free/N=1024 row permutation | Root difference 4.2915 micrometres exceeds the frozen 3-micrometre gate | Open; do not claim full large-batch isolation acceptance |
| Full scaling qualification | Historical curves exist; the final compensated asset has no new complete contact/scaling qualification | Not completed; historical curves are labeled as such |
| CoACD comparison | Four large convex hulls were changed by the SDK to 32–38 vertices | Comparison representation; not evidence of unchanged cooked hulls |
| Appearance | PreviewSurface, linear coverage 64/255; shadow exception limited to four ABXY BLEND domes | Not a complete glTF KHR dielectric-specular implementation |
| Generic build CLI / registry | Shared integration remains pending; readiness remains disabled | Use the dedicated example in this preview |
| Training and hardware calibration | Not run / not established | No RL performance or hardware-identified physics claim |

## L3 / R3 investigation record

The latest frozen run maintains probe contact throughout each 125-sample hold
window, without shell contact or saturation at the 16 N force cap. The scalar
signals agree with actual click displacement. This confirms a physical-response
problem rather than a canonical32 mapping error.

Nine completed diagnostic application windows tested the original SDF, unilateral
CoACD, prescribed axial force, temporary tilt restraint and direct axial loads.
None establishes a production fix. Diagnostic changes were not adopted. The
unmodified side in unilateral controls reproduced its original trace exactly.
The SAPIEN baseline also fails L3/R3, but its force-capped, nearly stationary
response differs from the Isaac oscillation; a common cause is not established.

The interaction between external loading and native implicit drives remains a
candidate explanation. A global solver-policy control was proposed but has not
been run or adopted. Further diagnosis is parked; do not silently enable that
policy, tune physical parameters or relax the frozen scoring thresholds.
