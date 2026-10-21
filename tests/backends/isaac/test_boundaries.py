"""Engine-free boundary regressions; native reviews live under experiments/isaac."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from xbox_gamepad_physics.isaac.builder import _axis_quaternion
from xbox_gamepad_physics.backends.common.transforms import rotate


@pytest.mark.parametrize('axis',[(1.,0.,0.),(-1.,0.,0.),
    (-.9999999999993869,-1.106527147132005e-6,4.128884582358239e-8),
    (6.1918180872594985e-6,6.503695254777861e-9,-.9999999999808307)])
def test_signed_and_near_antiparallel_axes_keep_source_direction(axis):
    # A tolerance-based parallel/antiparallel shortcut loses real source tilt.
    assert rotate(_axis_quaternion(axis),(1.,0.,0.))==pytest.approx(axis,abs=1e-14)


def test_plain_adapter_import_does_not_start_platform():
    code="import sys; import xbox_gamepad_physics.isaac; assert not {'pxr','torch','isaaclab','sapien','mujoco'}.intersection(sys.modules)"
    subprocess.run([sys.executable,'-c',code],check=True)


def test_preview_binding_message_does_not_block_loading(monkeypatch, capsys):
    from xbox_gamepad_physics.isaac import articulation
    expected = object()
    monkeypatch.setattr(articulation, 'IsaacGamepadHandle', lambda *args, **kwargs: expected)
    assert articulation.bind_articulation(object(), motion=object(), physical=object()) is expected
    message = capsys.readouterr().out
    assert len(message.splitlines()) == 1 and 'preview' in message
