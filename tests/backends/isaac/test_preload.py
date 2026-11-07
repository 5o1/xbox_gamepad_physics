"""The common affine spring is preserved at the Isaac native boundary."""
from types import SimpleNamespace

import pytest

from xbox_gamepad_physics.isaac.preload import passive_target, click_efforts, initialize_click_preload


def test_affine_click_law_uses_zero_drive_plus_constant_effort():
    law = SimpleNamespace(stiffness=SimpleNamespace(value=1000.),
                          neutral_target=SimpleNamespace(value=-.0074))
    physical = SimpleNamespace(return_laws={'left_stick_click': law, 'button_a': law})
    assert passive_target('left_stick_click', law) == 0.
    assert passive_target('button_a', law) == -.0074
    efforts = click_efforts(physical)
    assert efforts == {'left_stick_click': -7.4}
    for q in (0., .0002, .0004):
        assert efforts['left_stick_click']-1000*q == pytest.approx(1000*(-.0074-q))


def test_initialize_preload_keeps_nonclick_commands_and_persistent_lab_buffer():
    torch = pytest.importorskip('torch')
    target = torch.tensor([[2., 0., 0.], [3., 0., 0.]])
    art = SimpleNamespace(joint_names=['button_a', 'left_stick_click', 'right_stick_click'],
                          num_instances=2, device='cpu',
                          data=SimpleNamespace(joint_pos=torch.zeros_like(target), joint_effort_target=target))
    def set_target(values, joint_ids, env_ids=None):
        if env_ids is None:
            target[:, joint_ids] = values
        else:
            target[env_ids[:, None], joint_ids] = values
    submissions = []
    art.set_joint_effort_target = set_target
    art.root_physx_view = SimpleNamespace(set_dof_actuation_forces=lambda value, ids: submissions.append(value.clone()))
    initialize_click_preload(art, {'left_stick_click': -7.4, 'right_stick_click': -7.4})
    expected = torch.tensor([[2., -7.4, -7.4], [3., -7.4, -7.4]])
    torch.testing.assert_close(target, expected)
    torch.testing.assert_close(submissions[0], expected)
    # Reinstallation is idempotent rather than adding the bias twice.
    initialize_click_preload(art, {'left_stick_click': -7.4, 'right_stick_click': -7.4})
    torch.testing.assert_close(target, expected)
