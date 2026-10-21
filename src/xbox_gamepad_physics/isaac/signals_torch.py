"""Isaac tensor adapter for the common mapper, using float64 branch decisions.

Torch and CUDA are caller-provided dependencies. No application is launched.
The common mapper owns normalization, masks, events and inverse mapping. The
explicit decision mode disables its CPU per-row math.hypot boundary oracle;
D07 compares the CUDA result to Python on the identical representable inputs.
"""
from __future__ import annotations

import torch

from ..backends.common.signals_torch import (
    NamedJointBatch,
    SignalBatch,
    TorchSignalMapper as CommonTorchSignalMapper,
)


class IsaacTorchSignalMapper(CommonTorchSignalMapper):
    """Vectorized mapper retaining float32 storage with float64 arithmetic."""

    def __init__(self, motion, joint_names, *, device="cuda:0", dtype=torch.float32):
        if dtype != torch.float32:
            raise ValueError("Isaac B2 mapper requires float32 storage")
        super().__init__(motion, joint_names, device=device, dtype=dtype,
                         decision_mode="float64")


__all__ = ["IsaacTorchSignalMapper", "NamedJointBatch", "SignalBatch"]
