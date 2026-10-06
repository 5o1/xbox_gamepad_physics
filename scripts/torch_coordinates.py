"""Differentiable coordinate mapping matching viewer/rig.mjs, not physics.

Only configured channels are returned by the inverse. No values are invented
for unknown channels. Asymmetric stick mapping has a kink at zero; clipped
inverse has zero gradient outside its range. Neither is smoothed or given a
straight-through estimator. Parameters are fixed evidence-backed inputs.
"""
import math
import torch
from torch import nn


class CoordinateMap(nn.Module):
    def __init__(self, joints):
        super().__init__()
        if not joints:
            raise ValueError('No configured coordinates')
        used = set()
        for j in joints:
            c = j.get('channel')
            if type(c) is not int or c < 0 or c >= 21 or c in used:
                raise ValueError('Invalid/duplicate channel')
            used.add(c)
            for key in ('q0', 'q1'):
                v = j.get(key)
                if type(v) not in (int, float) or not math.isfinite(v):
                    raise ValueError(f'Missing/invalid {key}')
            if j['q0'] >= j['q1'] or (c < 4 and not j['q0'] < 0 < j['q1']):
                raise ValueError('Invalid coordinate interval')
            if not isinstance(j.get('evidence'), str) or not j['evidence'].strip():
                raise ValueError('Missing provenance')
        self.register_buffer('channels', torch.tensor([j['channel'] for j in joints], dtype=torch.long))
        self.register_buffer('q0', torch.tensor([j['q0'] for j in joints], dtype=torch.float64))
        self.register_buffer('q1', torch.tensor([j['q1'] for j in joints], dtype=torch.float64))

    def _check(self, x, width):
        if not isinstance(x, torch.Tensor) or not x.is_floating_point():
            raise ValueError('Expected floating tensor')
        if x.ndim < 1 or x.shape[-1] != width or not torch.isfinite(x).all():
            raise ValueError('Invalid tensor shape or nonfinite values')
        if x.device != self.channels.device:
            raise ValueError('Move CoordinateMap and input to the same device')

    def forward(self, state):
        """[...,21] normalized signals -> [...,J] configured coordinates."""
        self._check(state, 21)
        low = torch.cat((state.new_full((4,), -1), state.new_zeros(17)))
        if ((state < low) | (state > 1)).any():
            raise ValueError('Signal out of range')
        v = state.index_select(-1, self.channels)
        a, b = self.q0.to(v.dtype), self.q1.to(v.dtype)
        stick = torch.where(v < 0, -v*a, v*b)
        return torch.where(self.channels < 4, stick, a + v*(b-a))

    def inverse(self, coordinates):
        """[...,J] -> [...,J] signals in self.channels order; clips as viewer does."""
        self._check(coordinates, self.channels.numel())
        q = coordinates
        a, b = self.q0.to(q.dtype), self.q1.to(q.dtype)
        is_stick = self.channels < 4
        # Avoid division by zero even in inactive torch.where branches.
        neg_scale = torch.where(is_stick, -a, torch.ones_like(a))
        pos_scale = torch.where(is_stick, b, torch.ones_like(b))
        stick = torch.where(q < 0, q/neg_scale, q/pos_scale)
        signal = torch.where(is_stick, stick, (q-a)/(b-a))
        low = torch.where(is_stick, -torch.ones_like(a), torch.zeros_like(a))
        return torch.maximum(low, torch.minimum(torch.ones_like(b), signal))
