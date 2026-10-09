"""Minimal consumer module for RoboTwin ea8b211.

Copy this file into RoboTwin's ``envs/`` only when a concrete probe task is
useful. The package itself does not require task registration or this module.
"""

from envs._base_task import Base_Task

from xbox_gamepad_physics.robotwin import load_into_scene


class robotwin_gamepad_asset_probe(Base_Task):
    """Load the public backend during RoboTwin's normal ``load_actors`` phase."""

    def setup_demo(
        self,
        *,
        gamepad_pose,
        gamepad_fixed_root=True,
        gamepad_profile="full_controls",
        **kwargs,
    ):
        self._gamepad_pose = gamepad_pose
        self._gamepad_fixed_root = gamepad_fixed_root
        self._gamepad_profile = gamepad_profile
        super()._init_task_env_(**kwargs)

    def load_actors(self):
        self.gamepad = load_into_scene(
            scene=self.scene,
            pose=self._gamepad_pose,
            fixed_root=self._gamepad_fixed_root,
            profile=self._gamepad_profile,
        )

    def gamepad_observation(self):
        return self.gamepad.gamepad_state()
