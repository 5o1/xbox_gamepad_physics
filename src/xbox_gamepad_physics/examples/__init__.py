"""Installed examples, imported only when selected."""
from importlib import import_module

def lazy_experiment(module):
    def run(cfg, ctx):
        return import_module(module).run(cfg, ctx)
    return run

EXPERIMENTS = {name: lazy_experiment(__name__ + "." + name) for name in ("smoke", "render_review")}

EXPERIMENTS["teleop_replay"] = lazy_experiment("xbox_gamepad_physics.teleop.replay")
