"""Engine-independent Standard Gamepad state and channel layout.

The ordering follows the W3C Standard Gamepad mapping: four axes first,
followed by the seventeen standard buttons.  Button channels are analog values
in ``[0, 1]``; callers may apply their own pressed threshold where needed.
The physical Pair button is deliberately absent because the W3C standard
mapping does not assign it a channel.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import math
from typing import ClassVar, Iterable, Iterator, Mapping

from .errors import StateValidationError


@dataclass(frozen=True, slots=True)
class GamepadChannel:
    """One immutable entry in the canonical 21-channel layout."""

    name: str
    kind: str
    tensor_index: int
    standard_index: int
    minimum: float
    maximum: float


AXIS_NAMES = ("lx", "ly", "rx", "ry")
BUTTON_NAMES = (
    "a",
    "b",
    "x",
    "y",
    "left_shoulder",
    "right_shoulder",
    "left_trigger",
    "right_trigger",
    "view",
    "menu",
    "left_stick_click",
    "right_stick_click",
    "dpad_up",
    "dpad_down",
    "dpad_left",
    "dpad_right",
    "guide",
)
CHANNEL_NAMES = AXIS_NAMES + BUTTON_NAMES
AXIS_COUNT = len(AXIS_NAMES)
BUTTON_COUNT = len(BUTTON_NAMES)
CHANNEL_COUNT = len(CHANNEL_NAMES)

GAMEPAD_LAYOUT = tuple(
    GamepadChannel(
        name=name,
        kind="axis",
        tensor_index=tensor_index,
        standard_index=tensor_index,
        minimum=-1.0,
        maximum=1.0,
    )
    for tensor_index, name in enumerate(AXIS_NAMES)
) + tuple(
    GamepadChannel(
        name=name,
        kind="button",
        tensor_index=AXIS_COUNT + standard_index,
        standard_index=standard_index,
        minimum=0.0,
        maximum=1.0,
    )
    for standard_index, name in enumerate(BUTTON_NAMES)
)

_CHANNEL_BY_NAME: Mapping[str, GamepadChannel] = {
    channel.name: channel for channel in GAMEPAD_LAYOUT
}


def _validated_value(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StateValidationError(
            f"channel {name!r} must be a real number, got {type(value).__name__}"
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise StateValidationError(f"channel {name!r} must be finite")
    channel = _CHANNEL_BY_NAME[name]
    if not channel.minimum <= numeric <= channel.maximum:
        raise StateValidationError(
            f"channel {name!r}={numeric!r} is outside "
            f"[{channel.minimum}, {channel.maximum}]"
        )
    return numeric


@dataclass(frozen=True, slots=True)
class GamepadState:
    """Immutable state in canonical W3C axes-then-buttons order."""

    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    a: float = 0.0
    b: float = 0.0
    x: float = 0.0
    y: float = 0.0
    left_shoulder: float = 0.0
    right_shoulder: float = 0.0
    left_trigger: float = 0.0
    right_trigger: float = 0.0
    view: float = 0.0
    menu: float = 0.0
    left_stick_click: float = 0.0
    right_stick_click: float = 0.0
    dpad_up: float = 0.0
    dpad_down: float = 0.0
    dpad_left: float = 0.0
    dpad_right: float = 0.0
    guide: float = 0.0

    layout: ClassVar[tuple[GamepadChannel, ...]] = GAMEPAD_LAYOUT

    def __post_init__(self) -> None:
        for field in fields(self):
            object.__setattr__(
                self, field.name, _validated_value(field.name, getattr(self, field.name))
            )

    @classmethod
    def neutral(cls) -> "GamepadState":
        """Return the all-zero neutral Standard Gamepad state."""

        return cls()

    @classmethod
    def from_sequence(cls, values: Iterable[float]) -> "GamepadState":
        """Build a state from exactly 21 values in canonical layout order."""

        packed = tuple(values)
        if len(packed) != CHANNEL_COUNT:
            raise StateValidationError(
                f"expected {CHANNEL_COUNT} channels, got {len(packed)}"
            )
        return cls(**dict(zip(CHANNEL_NAMES, packed, strict=True)))

    @classmethod
    def from_mapping(cls, values: Mapping[str, float]) -> "GamepadState":
        """Build a state from a mapping containing every canonical channel."""

        missing = tuple(name for name in CHANNEL_NAMES if name not in values)
        extra = tuple(name for name in values if name not in _CHANNEL_BY_NAME)
        if missing or extra:
            raise StateValidationError(
                f"state mapping mismatch: missing={missing!r}, extra={extra!r}"
            )
        return cls(**{name: values[name] for name in CHANNEL_NAMES})

    @property
    def axes(self) -> tuple[float, ...]:
        return self.as_tuple()[:AXIS_COUNT]

    @property
    def buttons(self) -> tuple[float, ...]:
        return self.as_tuple()[AXIS_COUNT:]

    def as_tuple(self) -> tuple[float, ...]:
        """Return values in canonical tensor order without a tensor dependency."""

        return tuple(getattr(self, name) for name in CHANNEL_NAMES)

    def as_dict(self) -> dict[str, float]:
        """Return an insertion-ordered copy keyed by canonical channel name."""

        return dict(zip(CHANNEL_NAMES, self.as_tuple(), strict=True))

    def __iter__(self) -> Iterator[float]:
        return iter(self.as_tuple())

    def __len__(self) -> int:
        return CHANNEL_COUNT

    def __getitem__(self, index: int | slice) -> float | tuple[float, ...]:
        return self.as_tuple()[index]
