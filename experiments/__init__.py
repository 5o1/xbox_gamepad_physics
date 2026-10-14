"""Checkout experiments; registration never imports a selected implementation."""
from xbox_gamepad_physics.examples import EXPERIMENTS, lazy_experiment

def register_checkout_experiments():
    for name in ("drive_reach", "collision_check", "drop", "collision_overlay", "teleop_replay"):
        EXPERIMENTS.setdefault(name, lazy_experiment(__name__ + "." + name))

register_checkout_experiments()
