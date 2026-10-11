"""Checkout-only experiments; add each experiment's run function here."""

from typing import Callable

from .render_review import run as render_review
from .smoke import run as smoke
from .drive_reach import run as drive_reach
from .collision_check import run as collision_check
from .drop import run as drop
from .collision_overlay import run as collision_overlay


EXPERIMENTS: dict[str, Callable] = {
    "smoke": smoke,
    "render_review": render_review,
    "drive_reach": drive_reach,
    "collision_check": collision_check,
    "drop": drop,
    "collision_overlay": collision_overlay,
}
