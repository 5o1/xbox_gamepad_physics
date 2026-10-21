"""Compiled-name and caller collision-policy inspection without mutation."""
from __future__ import annotations
from xbox_gamepad_physics.backends.common.diagnostics import Finding


def diagnose(model, *, body_names, attach_visual=True, expected_external_masks=None, numerical_policy=None, sdf_policy=None):
    """Report native appearance limits and collisions against caller geometry.

    ``expected_external_masks`` maps caller geom names to requested contact
    booleans. Without a caller policy, overlapping bits are reported as shared
    allocation, rather than claiming that normal external contact is invalid.
    Explicit pairs can bypass ordinary mask and body-exclude filtering.
    """
    bodies = {int(model.body(name).id) for name in body_names}
    own = [i for i in range(model.ngeom) if int(model.geom_bodyid[i]) in bodies]
    collision = [i for i in own if int(model.geom_contype[i]) or int(model.geom_conaffinity[i])]
    findings = [Finding("named_bindings_complete", "info", "All manifest names were bound before diagnostics.")]
    if numerical_policy is None:
        from .numerics import numerical_policy as resolve_policy
        numerical_policy = resolve_policy()
    bound = numerical_policy['max_physics_timestep_s']
    from ._backend import require_mujoco
    mj = require_mujoco()
    recommended = numerical_policy['integrator']
    expected_integrator = {'discrete': mj.mjtIntegrator.mjINT_DISCRETE,
                           'implicitfast': mj.mjtIntegrator.mjINT_IMPLICITFAST}[recommended]
    refsafe = not bool(model.opt.disableflags & int(mj.mjtDisableBit.mjDSBL_REFSAFE))
    expected_refsafe = numerical_policy.get('refsafe', True)
    differs = (model.opt.timestep > bound or int(model.opt.integrator) != int(expected_integrator)
               or refsafe != expected_refsafe)
    findings.append(Finding('numerical_stability_timestep',
        'warning' if differs else 'info',
        f'Selected button/shaft-limit response uses timestep <= 0.0005 s, {recommended}, '
        f"refsafe {'enabled' if expected_refsafe else 'disabled'}; caller options are unchanged. "
        'This is a numerical stability policy, not hardware physical properties.',
        {'max_physics_timestep_s': bound, 'actual_timestep_s': float(model.opt.timestep),
         'recommended_integrator': recommended,
         'actual_integrator': mj.mjtIntegrator(int(model.opt.integrator)).name,
         'recommended_refsafe': expected_refsafe, 'actual_refsafe': refsafe,
         'approval_date': numerical_policy['approval_date']}))
    findings.append(Finding('geom_owned_contact_response', 'info',
        'Gamepad collision geoms carry their own solref/solmix. Equal-priority positive-format mixing uses solmix; friction coefficient mixing remains independent. Caller parameters are not edited. Native priority, direct-format, explicit-pair and global-override rules still apply.',
        {'solref': sorted({tuple(float(v) for v in model.geom_solref[g]) for g in collision}),
         'solmix': sorted({float(model.geom_solmix[g]) for g in collision})}))
    if sdf_policy is not None:
        findings.append(Finding('native_sdf_representation', 'info',
            'Native SDF is the default; mesh depth is selected before compilation. Caller search options are unchanged.',
            {'octree_maxdepth': sdf_policy['octree_maxdepth'],
             'actual_sdf_iterations': int(model.opt.sdf_iterations),
             'actual_sdf_initpoints': int(model.opt.sdf_initpoints),
             'standalone_sdf_iterations': sdf_policy['sdf_iterations'],
             'standalone_sdf_initpoints': sdf_policy['sdf_initpoints']}))
    shared = []
    expected = expected_external_masks or {}
    for external in range(model.ngeom):
        if external in own:
            continue
        name = model.geom(external).name
        allowed = any((int(model.geom_contype[g]) & int(model.geom_conaffinity[external])) or
                      (int(model.geom_contype[external]) & int(model.geom_conaffinity[g]))
                      for g in collision)
        if allowed:
            shared.append(name)
        if name in expected and bool(expected[name]) != bool(allowed):
            findings.append(Finding("caller_collision_policy_conflict", "error",
                "Compiled masks disagree with the caller's requested external contact.",
                {"geom": name, "requested": bool(expected[name]), "actual": bool(allowed)}))
    if shared:
        findings.append(Finding("caller_collision_bits_shared", "info",
            "Native masks permit external contact; the caller owns bit allocation.", {"geoms": shared}))
    for index in range(model.npair):
        pair = (int(model.pair_geom1[index]), int(model.pair_geom2[index]))
        if any(g in own for g in pair):
            findings.append(Finding("explicit_contact_pair", "warning",
                "An explicit pair involving this instance bypasses ordinary mask/exclude policy.",
                {"geom1": model.geom(pair[0]).name, "geom2": model.geom(pair[1]).name}))
    findings.append(Finding("appearance_classic_limits", "warning" if attach_visual else "info",
        "Classic rendering uses Phong shading and geom-level transparency sorting; source PBR is approximate."
        if attach_visual else "Visual geometry was explicitly omitted."))
    findings.append(Finding("native_contact_material", "warning",
        "Native numerical contact parameters are not measured Xbox material properties; consult mapping_report.json."))
    return tuple(findings)
