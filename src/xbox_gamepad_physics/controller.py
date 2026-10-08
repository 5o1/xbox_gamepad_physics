"""Simulator-independent mapping from mechanism state to gamepad signals."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from .errors import StateValidationError
from .state import (
    AXIS_NAMES,
    CHANNEL_NAMES,
    GamepadDeviceId,
    GamepadState,
    XBOX_ONE_S_CHANNELS,
)


@dataclass(frozen=True, slots=True)
class AxisSignalMapping:
    """Map one named mechanism coordinate to one canonical gamepad axis."""

    channel: str
    source: str
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class RadialSignalGroup:
    """Constrain two normalized axes to a circular signal envelope."""

    channels: tuple[str, str]
    radius: float


class GamepadSignalController:
    """Convert named mechanism coordinates into a canonical ``GamepadState``.

    Backends provide only named scalar coordinates. Normalization, saturation,
    radial constraints and output masks are owned here so RoboTwin and MuJoCo
    can share exactly the same signal semantics.
    """

    def __init__(
        self,
        *,
        device_id: int,
        device_channels: Iterable[str],
        axis_mappings: Iterable[AxisSignalMapping],
        radial_groups: Iterable[RadialSignalGroup] = (),
    ) -> None:
        channels = tuple(device_channels)
        unknown_device_channels = tuple(
            channel for channel in channels if channel not in CHANNEL_NAMES
        )
        if unknown_device_channels:
            raise StateValidationError(
                f"unknown device channels: {unknown_device_channels!r}"
            )
        if len(set(channels)) != len(channels):
            raise StateValidationError("duplicate device channels")

        mappings = tuple(axis_mappings)
        mapped_channels: set[str] = set()
        mapped_sources: set[str] = set()
        for mapping in mappings:
            if mapping.channel not in AXIS_NAMES[:4]:
                raise StateValidationError(
                    f"axis mapping channel {mapping.channel!r} is not a stick axis"
                )
            if mapping.channel not in channels:
                raise StateValidationError(
                    f"mapped channel {mapping.channel!r} is not exposed by the device"
                )
            if mapping.channel in mapped_channels:
                raise StateValidationError(
                    f"duplicate mapped channel {mapping.channel!r}"
                )
            if not isinstance(mapping.source, str) or not mapping.source:
                raise StateValidationError("axis mapping source must be non-empty")
            if mapping.source in mapped_sources:
                raise StateValidationError(
                    f"duplicate mapped source {mapping.source!r}"
                )
            if not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in (mapping.lower, mapping.upper)
            ):
                raise StateValidationError(
                    f"axis mapping {mapping.channel!r} needs finite limits"
                )
            if not mapping.lower < 0 < mapping.upper:
                raise StateValidationError(
                    f"axis mapping {mapping.channel!r} limits must straddle zero"
                )
            mapped_channels.add(mapping.channel)
            mapped_sources.add(mapping.source)

        groups = tuple(radial_groups)
        for group in groups:
            if len(group.channels) != 2:
                raise StateValidationError(
                    "radial group needs exactly two mapped channels"
                )
            first, second = group.channels
            if (
                first == second
                or first not in mapped_channels
                or second not in mapped_channels
            ):
                raise StateValidationError(
                    "radial group needs two distinct mapped channels"
                )
            if (
                isinstance(group.radius, bool)
                or not isinstance(group.radius, (int, float))
                or not math.isfinite(group.radius)
                or not 0 < group.radius <= 1
            ):
                raise StateValidationError("radial group radius must be in (0, 1]")

        if (
            isinstance(device_id, bool)
            or not isinstance(device_id, int)
            or device_id < 0
        ):
            raise StateValidationError("device_id must be a non-negative integer")
        self._device_id = int(device_id)
        self._device_channels = channels
        self._axis_mappings = mappings
        self._radial_groups = groups

    @classmethod
    def xbox_one_s(
        cls,
        axis_mappings: Iterable[AxisSignalMapping],
        radial_groups: Iterable[RadialSignalGroup] = (),
    ) -> "GamepadSignalController":
        return cls(
            device_id=GamepadDeviceId.XBOX_ONE_S,
            device_channels=XBOX_ONE_S_CHANNELS,
            axis_mappings=axis_mappings,
            radial_groups=radial_groups,
        )

    @property
    def axis_mappings(self) -> tuple[AxisSignalMapping, ...]:
        return self._axis_mappings

    @property
    def radial_groups(self) -> tuple[RadialSignalGroup, ...]:
        return self._radial_groups

    @property
    def available_channels(self) -> tuple[str, ...]:
        return tuple(mapping.channel for mapping in self._axis_mappings)

    def encode(
        self,
        source_positions: Mapping[str, float],
        *,
        task_channels: Iterable[str] | None = None,
    ) -> GamepadState:
        """Map one mechanism observation to normalized gamepad signals."""

        values: dict[str, float] = {}
        for mapping in self._axis_mappings:
            if mapping.source not in source_positions:
                raise StateValidationError(
                    f"missing mechanism coordinate {mapping.source!r}"
                )
            raw = source_positions[mapping.source]
            if (
                isinstance(raw, bool)
                or not isinstance(raw, (int, float))
                or not math.isfinite(raw)
            ):
                raise StateValidationError(
                    f"mechanism coordinate {mapping.source!r} must be finite"
                )
            scale = -mapping.lower if raw < 0 else mapping.upper
            values[mapping.channel] = max(-1.0, min(1.0, float(raw) / scale))

        for group in self._radial_groups:
            first, second = group.channels
            radius = math.hypot(values[first], values[second])
            if radius > group.radius:
                factor = group.radius / radius
                values[first] *= factor
                values[second] *= factor

        return GamepadState.from_mapping(
            values,
            device_id=self._device_id,
            available_channels=self.available_channels,
            task_channels=task_channels,
        )
