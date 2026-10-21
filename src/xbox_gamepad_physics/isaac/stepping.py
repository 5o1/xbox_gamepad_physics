"""Convenience stepping for caller-owned simulation and native articulations."""
from __future__ import annotations


def step(simulation, *, gamepads, render=False, nstep=1):
    """Flush, advance native physics and refresh listed articulation buffers.

    The caller creates/resets the scene and updates its other actors/sensors.
    Callers may perform the same SDK calls directly. Cone constraints live in
    PhysX; this helper never corrects their position or velocity residuals.
    """
    if isinstance(nstep, bool) or not isinstance(nstep, int) or nstep < 1:
        raise ValueError('nstep must be a positive integer')
    owners = tuple(getattr(handle, 'batch', handle) for handle in gamepads)
    if len({id(handle.articulation) for handle in owners}) != len(owners):
        raise ValueError('each native articulation must be listed once')
    dt = simulation.get_physics_dt()
    for _ in range(nstep):
        for handle in owners:
            handle.articulation.write_data_to_sim()
        simulation.step(render=False)
        for handle in owners:
            handle.articulation.update(dt)
        if render:
            simulation.render()
