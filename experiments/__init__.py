"""Checkout-only experiments; add each experiment's run function here."""

from typing import Callable

from .render_review import run as render_review
from .smoke import run as smoke


EXPERIMENTS: dict[str, Callable] = {
    "smoke": smoke,
    "render_review": render_review,
}
