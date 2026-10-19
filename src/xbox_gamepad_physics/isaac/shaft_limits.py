"""Read-only cone geometry and validation of caller-requested state writes.

The regular spherical joints in the USD supply all dynamic constraint response.
This module never solves impulses, changes poses or velocities, or runs during
a physics tick. Native solver residuals remain observable.
"""
from __future__ import annotations

import torch

from .constraints import joint_chain, require_supported_constraints


def _rotate(q, v):
    cross = torch.linalg.cross(q[..., 1:], v, dim=-1)
    return v + 2*(q[..., :1]*cross + torch.linalg.cross(q[..., 1:], cross, dim=-1))


def _multiply(a, b):
    return torch.cat((a[..., :1]*b[..., :1]-(a[..., 1:]*b[..., 1:]).sum(-1, keepdim=True),
        a[..., :1]*b[..., 1:]+b[..., :1]*a[..., 1:]+
        torch.linalg.cross(a[..., 1:], b[..., 1:], dim=-1)), dim=-1)


class ShaftLimits:
    """Validate explicit writes without modifying their requested state."""
    def __init__(self, articulation, motion):
        self.articulation = articulation
        self.limits = require_supported_constraints(motion)
        self.device = torch.device(articulation.device)
        self.chains = tuple(joint_chain(motion, limit) for limit in self.limits)
        self.columns = tuple(tuple(articulation.joint_names.index(j.name) for j in chain) for chain in self.chains)
        self.maximum = torch.tensor([x.maximum_rad for x in self.limits], dtype=torch.float64, device=self.device)
        self._fast = all(len(c) == 2 and c[0].axis == (0., 1., 0.) and c[1].axis == (1., 0., 0.)
            and all(j.origin_orientation_wxyz == (1., 0., 0., 0.) for j in c)
            and l.reference_axis == l.moving_axis == (0., 0., 1.) for c, l in zip(self.chains, self.limits))
        self._pair_columns = torch.tensor(self.columns, dtype=torch.int64, device=self.device) if self._fast else None
        self._parameters = tuple((
            torch.tensor(limit.reference_axis, device=self.device, dtype=torch.float64),
            torch.tensor(limit.moving_axis, device=self.device, dtype=torch.float64),
            tuple((torch.tensor(j.origin_orientation_wxyz, device=self.device, dtype=torch.float64),
                   torch.tensor(j.axis, device=self.device, dtype=torch.float64)/sum(x*x for x in j.axis)**.5)
                  for j in chain)) for limit, chain in zip(self.limits, self.chains))

    def geometry(self, positions):
        """Actual shaft angle and its gradient in native articulation order."""
        q = positions.to(torch.float64)
        if not self.limits:
            return q.new_empty((len(q), 0)), q.new_empty((len(q), 0, q.shape[1]))
        jacobian = q.new_zeros((len(q), len(self.limits), q.shape[1]))
        if self._fast:
            pair = q[:, self._pair_columns]
            sine, cosine = pair.sin(), pair.cos()
            dot = cosine.prod(-1)
            cross_norm = (sine[..., 0].square()+(cosine[..., 0]*sine[..., 1]).square()).sqrt()
            gradient = sine*cosine.flip(-1)/cross_norm.clamp_min(torch.finfo(q.dtype).tiny)[..., None]
            jacobian.scatter_(2, self._pair_columns[None].expand(len(q), -1, -1), gradient)
            return torch.atan2(cross_norm, dot), jacobian
        angles = []
        for column, indices in enumerate(self.columns):
            reference, moving, parameters = self._parameters[column]
            orientation = q.new_zeros((len(q), 4)); orientation[:, 0] = 1.
            axes = []
            for index, (origin, axis) in zip(indices, parameters):
                orientation = _multiply(orientation, origin.expand_as(orientation))
                axes.append(_rotate(orientation, axis.expand(len(q), -1)))
                half = .5*q[:, index:index+1]
                orientation = _multiply(orientation, torch.cat((half.cos(), half.sin()*axis), -1))
            moving = _rotate(orientation, moving.expand(len(q), -1))
            cross = torch.linalg.cross(reference.expand_as(moving), moving, dim=-1)
            cross_norm = torch.linalg.vector_norm(cross, dim=-1)
            angle = torch.atan2(cross_norm, (reference*moving).sum(-1))
            normal = cross/cross_norm.clamp_min(torch.finfo(q.dtype).tiny)[:, None]
            gradient = (torch.stack(axes, 1)*normal[:, None]).sum(-1)
            angles.append(angle)
            jacobian[:, column, indices] = gradient
        return torch.stack(angles, -1), jacobian

    def checked_state(self, positions, velocities):
        """Reject invalid caller writes and return the original tensor unchanged.

        Half-ULP coordinate uncertainty accounts for storage representation;
        it is not a tolerance for native dynamics or a modified cone angle.
        """
        if not self.limits or not len(positions):
            return positions
        angle, jacobian = self.geometry(positions)
        up = torch.nextafter(positions, torch.full_like(positions, float('inf')))
        down = torch.nextafter(positions, torch.full_like(positions, -float('inf')))
        half_ulp = (up.double()-down.double())*.25
        uncertainty = (jacobian.abs()*half_ulp[:, None]).sum(-1)+64*torch.finfo(torch.float64).eps
        outward = (jacobian*velocities.double()[:, None]).sum(-1)
        invalid = (angle > self.maximum+uncertainty) | ((angle >= self.maximum-uncertainty) & (outward > 0.))
        if bool(invalid.any()):
            raise ValueError('state violates the hard shaft cone or has outward boundary velocity')
        return positions

    def validate_initial_state(self):
        if self.limits:
            art = self.articulation
            self.checked_state(art.data.joint_pos, art.data.joint_vel)
