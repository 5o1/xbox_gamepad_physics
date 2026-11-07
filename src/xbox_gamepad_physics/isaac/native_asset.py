"""Isaac Lab asset lifecycle adapter; import only after AppLauncher.

InteractiveScene honors cfg.class_type. Direct users should construct
cfg.class_type(cfg), rather than Articulation(cfg), for automatic preload.
AssetBase's physics-play initialization callback invokes _initialize_impl after
PhysX becomes available. Reinitialization therefore reinstalls the constant.
"""
from isaaclab.assets import Articulation, ArticulationCfg
from isaaclab.utils import configclass

from .preload import initialize_click_preload


class IsaacGamepadArticulation(Articulation):
    def _initialize_impl(self):
        super()._initialize_impl()
        initialize_click_preload(self, self.cfg.click_preload_efforts)

@configclass
class IsaacGamepadArticulationCfg(ArticulationCfg):
    class_type: type = IsaacGamepadArticulation
    click_preload_efforts: dict[str, float] = {}
