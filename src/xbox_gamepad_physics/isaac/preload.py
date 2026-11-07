"""Translate the common affine click spring to native zero-target plus effort.

The frozen common rest position encodes F=k*(rest-q). Isaac's TGS needs
rest=0 in the force drive, with the constant k*rest in generalized effort.
No timestep callback, displacement feedback or signal threshold is involved.
"""
from __future__ import annotations


def passive_target(name, law):
    return 0. if name.endswith('_stick_click') else law.neutral_target.value


def click_efforts(physical):
    return {name: law.stiffness.value * law.neutral_target.value
            for name, law in physical.return_laws.items() if name.endswith('_stick_click')}


def initialize_click_preload(articulation, efforts, *, env_ids=None):
    """Set Lab's persistent effort buffer and submit native effort once.

    Subsequent ordinary write_data_to_sim calls preserve these values. A caller
    assigning new effort targets to click joints replaces them and must include
    this bias again. An external plain Articulation can call this after sim.reset
    (or bind a gamepad handle); the cfg.class_type asset does it automatically.
    """
    import torch
    if not efforts:
        return
    names = tuple(articulation.joint_names)
    columns = [names.index(name) for name in efforts]
    values = torch.tensor(list(efforts.values()), device=articulation.device,
                          dtype=articulation.data.joint_pos.dtype)
    articulation.set_joint_effort_target(values, joint_ids=columns, env_ids=env_ids)
    # Submit efforts only: initialization must not flush unrelated external
    # wrenches or position targets. Lab will submit the same buffer next tick.
    indices = torch.arange(articulation.num_instances, device=articulation.device, dtype=torch.int64)
    articulation.root_physx_view.set_dof_actuation_forces(
        articulation.data.joint_effort_target, indices)
