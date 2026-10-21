"""D07 validates CUDA branches against scalar Python on identical float32 q."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


def test_cuda_mapper_matches_python_branches():
    torch = pytest.importorskip('torch')
    if not torch.cuda.is_available():
        pytest.skip('D07 requires the external CUDA runtime')
    root = Path(__file__).resolve().parents[3]
    motion_path = Path(os.environ.get('XGP_B2_MOTION',
        str(root / 'build/resources/common/xbox_one_s/motion/full_controls.json')))
    if not motion_path.is_file():
        pytest.skip('Set XGP_B2_MOTION to prepared common motion data')
    spec = importlib.util.spec_from_file_location('check_mapper_b2', root / 'experiments/isaac/check_mapper_b2.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from xbox_gamepad_physics.motion import motion_from_dict
    motion = motion_from_dict(json.loads(motion_path.read_text()))
    result = module.check_mapper(motion)
    assert result['branch_mismatches'] == 0
    assert result['asymmetric_partial']['branch_mismatches'] == 0
