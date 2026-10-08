"""Engine-independent gamepad tensor contract for learning systems.

The fixed 32-value layout is a versioned concatenation of the six axes and
twenty-six buttons in SDL3's standard gamepad enums. SDL defines axes and
buttons as separate arrays; this module places axes first and buttons second.

Zero padding alone is ambiguous because zero is also a valid neutral control
value. Every state therefore carries both a device availability mask and a
task mask. The physical Pair button is device management rather than a game
control and is deliberately absent from the SDL3 core layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
from typing import ClassVar, Iterable, Iterator, Mapping

from .errors import StateValidationError


TENSOR_LAYOUT_ID = "sdl3-gamepad-core-v1"

# Keep these names and their order aligned with SDL_GamepadAxis. The shorter
# browser names (lx, ly, rx, ry) belong in boundary adapters, not this contract.
AXIS_NAMES = (
    "left_x",
    "left_y",
    "right_x",
    "right_y",
    "left_trigger",
    "right_trigger",
)

# Keep these names and their order aligned with SDL_GamepadButton.
BUTTON_NAMES = (
    "south",
    "east",
    "west",
    "north",
    "back",
    "guide",
    "start",
    "left_stick",
    "right_stick",
    "left_shoulder",
    "right_shoulder",
    "dpad_up",
    "dpad_down",
    "dpad_left",
    "dpad_right",
    "misc1",
    "right_paddle1",
    "left_paddle1",
    "right_paddle2",
    "left_paddle2",
    "touchpad",
    "misc2",
    "misc3",
    "misc4",
    "misc5",
    "misc6",
)

CHANNEL_NAMES = AXIS_NAMES + BUTTON_NAMES
AXIS_COUNT = len(AXIS_NAMES)
BUTTON_COUNT = len(BUTTON_NAMES)
CHANNEL_COUNT = len(CHANNEL_NAMES)


class GamepadDeviceId(IntEnum):
    """Stable IDs used by the v1 tensor contract."""

    UNKNOWN = 0
    XBOX_ONE_S = 1


@dataclass(frozen=True, slots=True)
class GamepadChannel:
    """One immutable channel in the canonical tensor layout."""

    name: str
    kind: str
    tensor_index: int
    standard_index: int
    minimum: float
    maximum: float


GAMEPAD_LAYOUT = tuple(
    GamepadChannel(
        name=name,
        kind="axis",
        tensor_index=tensor_index,
        standard_index=tensor_index,
        minimum=0.0 if name.endswith("_trigger") else -1.0,
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

# Xbox One S controls that have a semantic slot in the SDL3 core. Pair is not
# included. This is the capability mask for a complete device; a partial
# simulator asset must provide a narrower availability mask.
XBOX_ONE_S_CHANNELS = (
    "left_x",
    "left_y",
    "right_x",
    "right_y",
    "left_trigger",
    "right_trigger",
    "south",
    "east",
    "west",
    "north",
    "back",
    "guide",
    "start",
    "left_stick",
    "right_stick",
    "left_shoulder",
    "right_shoulder",
    "dpad_up",
    "dpad_down",
    "dpad_left",
    "dpad_right",
)

# Boundary order returned by a browser with ``mapping == "standard"``:
# four axes followed by seventeen button values. It is intentionally not the
# canonical learning layout.
W3C_STANDARD_TO_CANONICAL = (
    "left_x",
    "left_y",
    "right_x",
    "right_y",
    "south",
    "east",
    "west",
    "north",
    "left_shoulder",
    "right_shoulder",
    "left_trigger",
    "right_trigger",
    "back",
    "start",
    "left_stick",
    "right_stick",
    "dpad_up",
    "dpad_down",
    "dpad_left",
    "dpad_right",
    "guide",
)


def _validated_mask(name: str, values: Iterable[bool]) -> tuple[bool, ...]:
    packed = tuple(values)
    if len(packed) != CHANNEL_COUNT:
        raise StateValidationError(
            f"{name} must contain {CHANNEL_COUNT} entries, got {len(packed)}"
        )
    if any(type(value) is not bool for value in packed):
        raise StateValidationError(f"{name} entries must be bool")
    return packed


def _mask_from_names(names: Iterable[str], label: str) -> tuple[bool, ...]:
    packed = tuple(names)
    unknown = tuple(name for name in packed if name not in _CHANNEL_BY_NAME)
    if unknown:
        raise StateValidationError(f"unknown {label} channels: {unknown!r}")
    if len(set(packed)) != len(packed):
        raise StateValidationError(f"duplicate {label} channels")
    selected = set(packed)
    return tuple(name in selected for name in CHANNEL_NAMES)


def _validated_value(channel: GamepadChannel, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StateValidationError(
            f"channel {channel.name!r} must be a real number, "
            f"got {type(value).__name__}"
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise StateValidationError(f"channel {channel.name!r} must be finite")
    if not channel.minimum <= numeric <= channel.maximum:
        raise StateValidationError(
            f"channel {channel.name!r}={numeric!r} is outside "
            f"[{channel.minimum}, {channel.maximum}]"
        )
    return numeric


@dataclass(frozen=True, slots=True)
class GamepadState:
    """A fixed-width gamepad tensor with explicit validity information.

    ``values`` always has 32 entries in :data:`GAMEPAD_LAYOUT` order. Values
    unavailable in the current device or simulator profile must be zero.
    ``task_mask`` is an additional subset selecting channels used by the
    current task; it never changes what the device physically exposes.
    """

    values: tuple[float, ...]
    available_mask: tuple[bool, ...]
    task_mask: tuple[bool, ...]
    device_id: int

    layout: ClassVar[tuple[GamepadChannel, ...]] = GAMEPAD_LAYOUT
    layout_id: ClassVar[str] = TENSOR_LAYOUT_ID

    def __post_init__(self) -> None:
        packed_values = tuple(self.values)
        if len(packed_values) != CHANNEL_COUNT:
            raise StateValidationError(
                f"values must contain {CHANNEL_COUNT} channels, "
                f"got {len(packed_values)}"
            )
        available = _validated_mask("available_mask", self.available_mask)
        task = _validated_mask("task_mask", self.task_mask)
        if isinstance(self.device_id, bool) or not isinstance(self.device_id, int):
            raise StateValidationError("device_id must be an integer")
        if self.device_id < 0:
            raise StateValidationError("device_id must be non-negative")

        checked: list[float] = []
        for channel, value, is_available, is_task in zip(
            GAMEPAD_LAYOUT, packed_values, available, task, strict=True
        ):
            numeric = _validated_value(channel, value)
            if not is_available and numeric != 0.0:
                raise StateValidationError(
                    f"unavailable channel {channel.name!r} must be zero"
                )
            if is_task and not is_available:
                raise StateValidationError(
                    f"task channel {channel.name!r} is unavailable"
                )
            checked.append(numeric)

        object.__setattr__(self, "values", tuple(checked))
        object.__setattr__(self, "available_mask", available)
        object.__setattr__(self, "task_mask", task)
        object.__setattr__(self, "device_id", int(self.device_id))

    @classmethod
    def neutral(
        cls,
        *,
        device_id: int = GamepadDeviceId.UNKNOWN,
        available_channels: Iterable[str] = (),
        task_channels: Iterable[str] | None = None,
    ) -> "GamepadState":
        """Create an all-zero state with explicit capability and task masks."""

        available_names = tuple(available_channels)
        task_names = available_names if task_channels is None else tuple(task_channels)
        return cls(
            values=(0.0,) * CHANNEL_COUNT,
            available_mask=_mask_from_names(available_names, "available"),
            task_mask=_mask_from_names(task_names, "task"),
            device_id=device_id,
        )

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, float],
        *,
        device_id: int,
        available_channels: Iterable[str],
        task_channels: Iterable[str] | None = None,
    ) -> "GamepadState":
        """Create a state from named values and explicit channel sets.

        Available channels omitted from ``values`` take their neutral value.
        Supplying a value for an unavailable channel is rejected, including
        when that value happens to be zero.
        """

        extra = tuple(name for name in values if name not in _CHANNEL_BY_NAME)
        if extra:
            raise StateValidationError(f"unknown value channels: {extra!r}")
        available_names = tuple(available_channels)
        available_set = set(available_names)
        unavailable_values = tuple(name for name in values if name not in available_set)
        if unavailable_values:
            raise StateValidationError(
                f"values supplied for unavailable channels: {unavailable_values!r}"
            )
        packed = tuple(values.get(name, 0.0) for name in CHANNEL_NAMES)
        task_names = available_names if task_channels is None else tuple(task_channels)
        return cls(
            values=packed,
            available_mask=_mask_from_names(available_names, "available"),
            task_mask=_mask_from_names(task_names, "task"),
            device_id=device_id,
        )

    @classmethod
    def xbox_one_s(
        cls,
        values: Mapping[str, float] | None = None,
        *,
        available_channels: Iterable[str] = XBOX_ONE_S_CHANNELS,
        task_channels: Iterable[str] | None = None,
    ) -> "GamepadState":
        """Create an Xbox One S state in the shared 32-channel layout."""

        available_names = tuple(available_channels)
        unsupported = tuple(
            name for name in available_names if name not in XBOX_ONE_S_CHANNELS
        )
        if unsupported:
            raise StateValidationError(
                f"Xbox One S does not expose channels: {unsupported!r}"
            )
        return cls.from_mapping(
            {} if values is None else values,
            device_id=GamepadDeviceId.XBOX_ONE_S,
            available_channels=available_names,
            task_channels=task_channels,
        )

    @classmethod
    def from_w3c_standard(
        cls,
        values: Iterable[float],
        available_mask: Iterable[bool],
        *,
        device_id: int,
        task_channels: Iterable[str] | None = None,
    ) -> "GamepadState":
        """Adapt the browser's 21-value Standard Gamepad transport.

        The availability mask is mandatory because browsers and operating
        systems may omit the Guide button while still returning a zero value.
        """

        packed_values = tuple(values)
        packed_available = tuple(available_mask)
        boundary_count = len(W3C_STANDARD_TO_CANONICAL)
        if len(packed_values) != boundary_count:
            raise StateValidationError(
                f"W3C values must contain {boundary_count} entries, "
                f"got {len(packed_values)}"
            )
        if len(packed_available) != boundary_count:
            raise StateValidationError(
                f"W3C available_mask must contain {boundary_count} entries, "
                f"got {len(packed_available)}"
            )
        if any(type(value) is not bool for value in packed_available):
            raise StateValidationError("W3C available_mask entries must be bool")

        available_names = tuple(
            name
            for name, available in zip(
                W3C_STANDARD_TO_CANONICAL, packed_available, strict=True
            )
            if available
        )
        unavailable_nonzero = tuple(
            name
            for name, value, available in zip(
                W3C_STANDARD_TO_CANONICAL,
                packed_values,
                packed_available,
                strict=True,
            )
            if not available and value != 0.0
        )
        if unavailable_nonzero:
            raise StateValidationError(
                "W3C unavailable channels must be zero: "
                f"{unavailable_nonzero!r}"
            )
        mapped_values = {
            name: value
            for name, value, available in zip(
                W3C_STANDARD_TO_CANONICAL,
                packed_values,
                packed_available,
                strict=True,
            )
            if available
        }
        return cls.from_mapping(
            mapped_values,
            device_id=device_id,
            available_channels=available_names,
            task_channels=task_channels,
        )

    @property
    def action_mask(self) -> tuple[bool, ...]:
        """Mask used for action loss and execution (availability AND task)."""

        return tuple(
            available and task
            for available, task in zip(
                self.available_mask, self.task_mask, strict=True
            )
        )

    @property
    def action_mask_values(self) -> tuple[float, ...]:
        """Numeric action mask suitable for conversion by Torch, JAX or NumPy."""

        return tuple(float(value) for value in self.action_mask)

    @property
    def masked_action_values(self) -> tuple[float, ...]:
        """Return values with all non-action channels forced to zero."""

        return tuple(
            value if enabled else 0.0
            for value, enabled in zip(self.values, self.action_mask, strict=True)
        )

    def channel(self, name: str) -> float:
        try:
            index = _CHANNEL_BY_NAME[name].tensor_index
        except KeyError as error:
            raise KeyError(f"unknown gamepad channel {name!r}") from error
        return self.values[index]

    def is_available(self, name: str) -> bool:
        try:
            index = _CHANNEL_BY_NAME[name].tensor_index
        except KeyError as error:
            raise KeyError(f"unknown gamepad channel {name!r}") from error
        return self.available_mask[index]

    def is_task_channel(self, name: str) -> bool:
        try:
            index = _CHANNEL_BY_NAME[name].tensor_index
        except KeyError as error:
            raise KeyError(f"unknown gamepad channel {name!r}") from error
        return self.task_mask[index]

    def as_dict(self) -> dict[str, float]:
        """Return an insertion-ordered value mapping in tensor order."""

        return dict(zip(CHANNEL_NAMES, self.values, strict=True))

    def __iter__(self) -> Iterator[float]:
        return iter(self.values)

    def __len__(self) -> int:
        return CHANNEL_COUNT

    def __getitem__(self, index: int | slice) -> float | tuple[float, ...]:
        return self.values[index]
