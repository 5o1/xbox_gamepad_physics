"""Simulator-independent mapping from mechanism state to gamepad signals."""

from __future__ import annotations

from dataclasses import dataclass
import math
import json
from pathlib import Path
from typing import Iterable, Mapping

from .errors import StateValidationError
from .state import (
    AXIS_NAMES,
    CHANNEL_NAMES,
    GamepadDeviceId,
    GamepadState,
    XBOX_ONE_S_CHANNELS,
)


def _dpad_threshold_from_record() -> float:
    # Checkout uses the authorized reference record. Code-only installations
    # read the corresponding signal_policy record from their motion resource.
    reference = Path(__file__).resolve().parents[2] / "references/full_controls.json"
    if reference.is_file():
        record = json.loads(reference.read_text(encoding="utf-8"))
    else:
        from .resources import load_json_resource
        record = load_json_resource("common", "xbox_one_s", "motion/full_controls.json")
    try:
        value = record["signal_policy"]["dpad_contact_closure"]["threshold"]
    except KeyError as error:
        raise StateValidationError("D-pad contact threshold is missing from the reference/motion resource; update the signal-policy record") from error
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 1:
        raise StateValidationError("D-pad contact threshold must be a finite normalized fraction in (0, 1]")
    return float(value)


def _finite_limits(lower: object, upper: object) -> bool:
    return all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        for value in (lower, upper)
    )


def _valid_radius(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and 0 < value <= 1
    )


def _valid_neutral_epsilon(value: object, limit: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and 0 <= value < limit
    )


def _source_value(source_positions: Mapping[str, float], source: str) -> float:
    if source not in source_positions:
        raise StateValidationError(f"missing mechanism coordinate {source!r}")
    raw = source_positions[source]
    if (
        isinstance(raw, bool)
        or not isinstance(raw, (int, float))
        or not math.isfinite(raw)
    ):
        raise StateValidationError(f"mechanism coordinate {source!r} must be finite")
    return float(raw)


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
    neutral_epsilon: float = 0.0


@dataclass(frozen=True, slots=True)
class ScalarSignalMapping:
    """Map a one-sided mechanism coordinate to a [0, 1] channel."""

    channel: str
    source: str
    lower: float
    upper: float
    neutral_epsilon: float = 0.0


@dataclass(frozen=True, slots=True)
class SplitSignalMapping:
    """Split a signed mechanism coordinate into negative/positive buttons."""

    negative_channel: str
    positive_channel: str
    source: str
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class RadialSourceGroup:
    """Constrain two normalized signed mechanism coordinates before splitting."""

    sources: tuple[str, str]
    radius: float
    neutral_epsilon: float = 0.0


@dataclass(frozen=True, slots=True)
class PhysicalEventMapping:
    """Map a mechanism coordinate to a non-game device event."""

    event: str
    source: str
    lower: float
    upper: float


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
        scalar_mappings: Iterable[ScalarSignalMapping] = (),
        split_mappings: Iterable[SplitSignalMapping] = (),
        radial_source_groups: Iterable[RadialSourceGroup] = (),
        physical_event_mappings: Iterable[PhysicalEventMapping] = (),
        signal_policy: Mapping[str, object] | None = None,
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
        scalar = tuple(scalar_mappings)
        split = tuple(split_mappings)
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
            if not _finite_limits(mapping.lower, mapping.upper):
                raise StateValidationError(
                    f"axis mapping {mapping.channel!r} needs finite limits"
                )
            if not mapping.lower < 0 < mapping.upper:
                raise StateValidationError(
                    f"axis mapping {mapping.channel!r} limits must straddle zero"
                )
            mapped_channels.add(mapping.channel)
            mapped_sources.add(mapping.source)

        for mapping in scalar:
            if mapping.channel not in channels:
                raise StateValidationError(
                    f"mapped channel {mapping.channel!r} is not exposed by the device"
                )
            if mapping.channel in mapped_channels:
                raise StateValidationError(
                    f"duplicate mapped channel {mapping.channel!r}"
                )
            if not isinstance(mapping.source, str) or not mapping.source:
                raise StateValidationError("scalar mapping source must be non-empty")
            if mapping.source in mapped_sources:
                raise StateValidationError(
                    f"duplicate mapped source {mapping.source!r}"
                )
            if not _finite_limits(mapping.lower, mapping.upper):
                raise StateValidationError(
                    f"scalar mapping {mapping.channel!r} needs finite limits"
                )
            if not mapping.lower < mapping.upper:
                raise StateValidationError(
                    f"scalar mapping {mapping.channel!r} lower must be below upper"
                )
            if not _valid_neutral_epsilon(mapping.neutral_epsilon, 1.0):
                raise StateValidationError(
                    f"scalar mapping {mapping.channel!r} neutral_epsilon must be in [0, 1)"
                )
            mapped_channels.add(mapping.channel)
            mapped_sources.add(mapping.source)

        for mapping in split:
            output_channels = (mapping.negative_channel, mapping.positive_channel)
            if output_channels[0] == output_channels[1]:
                raise StateValidationError("split mapping channels must be distinct")
            for channel in output_channels:
                if channel not in channels:
                    raise StateValidationError(
                        f"mapped channel {channel!r} is not exposed by the device"
                    )
                if channel in mapped_channels:
                    raise StateValidationError(f"duplicate mapped channel {channel!r}")
            if not isinstance(mapping.source, str) or not mapping.source:
                raise StateValidationError("split mapping source must be non-empty")
            if mapping.source in mapped_sources:
                raise StateValidationError(
                    f"duplicate mapped source {mapping.source!r}"
                )
            if not _finite_limits(mapping.lower, mapping.upper):
                raise StateValidationError(
                    f"split mapping {mapping.source!r} needs finite limits"
                )
            if not mapping.lower < 0 < mapping.upper:
                raise StateValidationError(
                    f"split mapping {mapping.source!r} limits must straddle zero"
                )
            mapped_channels.update(output_channels)
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
            if not _valid_radius(group.radius):
                raise StateValidationError("radial group radius must be in (0, 1]")
            if not _valid_neutral_epsilon(group.neutral_epsilon, group.radius):
                raise StateValidationError(
                    "radial group neutral_epsilon must be in [0, radius)"
                )

        source_groups = tuple(radial_source_groups)
        split_sources = {mapping.source for mapping in split}
        for group in source_groups:
            if len(group.sources) != 2:
                raise StateValidationError(
                    "radial source group needs exactly two mapped sources"
                )
            first, second = group.sources
            if (
                first == second
                or first not in split_sources
                or second not in split_sources
            ):
                raise StateValidationError(
                    "radial source group needs two distinct split-mapped sources"
                )
            if not _valid_radius(group.radius):
                raise StateValidationError(
                    "radial source group radius must be in (0, 1]"
                )
            if not _valid_neutral_epsilon(group.neutral_epsilon, group.radius):
                raise StateValidationError(
                    "radial source group neutral_epsilon must be in [0, radius)"
                )

        events = tuple(physical_event_mappings)
        event_names: set[str] = set()
        for mapping in events:
            if not isinstance(mapping.event, str) or not mapping.event:
                raise StateValidationError("physical event name must be non-empty")
            if mapping.event in event_names:
                raise StateValidationError(f"duplicate physical event {mapping.event!r}")
            if not isinstance(mapping.source, str) or not mapping.source:
                raise StateValidationError("physical event source must be non-empty")
            if not _finite_limits(mapping.lower, mapping.upper):
                raise StateValidationError(
                    f"physical event {mapping.event!r} needs finite limits"
                )
            if not mapping.lower < mapping.upper:
                raise StateValidationError(
                    f"physical event {mapping.event!r} lower must be below upper"
                )
            event_names.add(mapping.event)

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
        self._scalar_mappings = scalar
        self._split_mappings = split
        self._radial_source_groups = source_groups
        self._physical_event_mappings = events
        self._dpad_contact_threshold = None
        if any(c.startswith("dpad_") for c in mapped_channels):
            if signal_policy is None:
                self._dpad_contact_threshold = _dpad_threshold_from_record()
            else:
                try:
                    threshold = signal_policy["dpad_contact_closure"]["threshold"]
                except (KeyError, TypeError) as error:
                    raise StateValidationError("signal_policy needs dpad_contact_closure.threshold") from error
                if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                        or not math.isfinite(threshold) or not 0 < threshold <= 1):
                    raise StateValidationError("D-pad contact threshold must be finite in (0, 1]")
                self._dpad_contact_threshold = float(threshold)

    @classmethod
    def xbox_one_s(
        cls,
        axis_mappings: Iterable[AxisSignalMapping],
        radial_groups: Iterable[RadialSignalGroup] = (),
        scalar_mappings: Iterable[ScalarSignalMapping] = (),
        split_mappings: Iterable[SplitSignalMapping] = (),
        radial_source_groups: Iterable[RadialSourceGroup] = (),
        physical_event_mappings: Iterable[PhysicalEventMapping] = (),
        *,
        signal_policy: Mapping[str, object] | None = None,
    ) -> "GamepadSignalController":
        return cls(
            device_id=GamepadDeviceId.XBOX_ONE_S,
            device_channels=XBOX_ONE_S_CHANNELS,
            axis_mappings=axis_mappings,
            radial_groups=radial_groups,
            scalar_mappings=scalar_mappings,
            split_mappings=split_mappings,
            radial_source_groups=radial_source_groups,
            physical_event_mappings=physical_event_mappings,
            signal_policy=signal_policy,
        )

    @property
    def dpad_contact_threshold(self) -> float | None:
        return self._dpad_contact_threshold

    @property
    def axis_mappings(self) -> tuple[AxisSignalMapping, ...]:
        return self._axis_mappings

    @property
    def radial_groups(self) -> tuple[RadialSignalGroup, ...]:
        return self._radial_groups

    @property
    def scalar_mappings(self) -> tuple[ScalarSignalMapping, ...]:
        return self._scalar_mappings

    @property
    def split_mappings(self) -> tuple[SplitSignalMapping, ...]:
        return self._split_mappings

    @property
    def radial_source_groups(self) -> tuple[RadialSourceGroup, ...]:
        return self._radial_source_groups

    @property
    def physical_event_mappings(self) -> tuple[PhysicalEventMapping, ...]:
        return self._physical_event_mappings

    @property
    def available_channels(self) -> tuple[str, ...]:
        mapped = [mapping.channel for mapping in self._axis_mappings]
        mapped.extend(mapping.channel for mapping in self._scalar_mappings)
        for mapping in self._split_mappings:
            mapped.extend((mapping.negative_channel, mapping.positive_channel))
        return tuple(mapped)

    def encode(
        self,
        source_positions: Mapping[str, float],
        *,
        task_channels: Iterable[str] | None = None,
    ) -> GamepadState:
        """Map one mechanism observation to normalized gamepad signals."""

        values: dict[str, float] = {}
        for mapping in self._axis_mappings:
            raw = _source_value(source_positions, mapping.source)
            scale = -mapping.lower if raw < 0 else mapping.upper
            values[mapping.channel] = max(-1.0, min(1.0, float(raw) / scale))

        for mapping in self._scalar_mappings:
            raw = _source_value(source_positions, mapping.source)
            normalized = (raw - mapping.lower) / (mapping.upper - mapping.lower)
            normalized = max(0.0, min(1.0, normalized))
            values[mapping.channel] = (
                0.0 if normalized <= mapping.neutral_epsilon else normalized
            )

        split_values = {}
        for mapping in self._split_mappings:
            raw = _source_value(source_positions, mapping.source)
            scale = -mapping.lower if raw < 0 else mapping.upper
            split_values[mapping.source] = max(-1.0, min(1.0, raw / scale))

        for group in self._radial_source_groups:
            first, second = group.sources
            radius = math.hypot(split_values[first], split_values[second])
            if radius <= group.neutral_epsilon:
                split_values[first] = 0.0
                split_values[second] = 0.0
            elif radius > group.radius:
                factor = group.radius / radius
                split_values[first] *= factor
                split_values[second] *= factor

        for mapping in self._split_mappings:
            signed = split_values[mapping.source]
            values[mapping.negative_channel] = max(0.0, -signed)
            values[mapping.positive_channel] = max(0.0, signed)

        for group in self._radial_groups:
            first, second = group.channels
            radius = math.hypot(values[first], values[second])
            if radius <= group.neutral_epsilon:
                values[first] = 0.0
                values[second] = 0.0
            elif radius > group.radius:
                factor = group.radius / radius
                values[first] *= factor
                values[second] *= factor

        # Independent contact closure after split/deadzone/radial processing.
        # Keep continuous amplitudes; genuine diagonal contacts can both close.
        for channel in ("dpad_up", "dpad_down", "dpad_left", "dpad_right"):
            if channel in values and values[channel] < self._dpad_contact_threshold:
                values[channel] = 0.0

        return GamepadState.from_mapping(
            values,
            device_id=self._device_id,
            available_channels=self.available_channels,
            task_channels=task_channels,
        )

    def encode_physical_events(
        self, source_positions: Mapping[str, float]
    ) -> dict[str, float]:
        """Return normalized physical-only events outside the game tensor."""

        values = {}
        for mapping in self._physical_event_mappings:
            raw = _source_value(source_positions, mapping.source)
            normalized = (raw - mapping.lower) / (mapping.upper - mapping.lower)
            values[mapping.event] = max(0.0, min(1.0, normalized))
        return values

    def decode_joint_targets(self, state: GamepadState) -> dict[str, float]:
        """Convert canonical gamepad values to named mechanism coordinates."""

        targets = {}
        for mapping in self._axis_mappings:
            value = state.channel(mapping.channel)
            scale = -mapping.lower if value < 0 else mapping.upper
            targets[mapping.source] = value * scale
        for mapping in self._scalar_mappings:
            value = state.channel(mapping.channel)
            targets[mapping.source] = (
                mapping.lower + value * (mapping.upper - mapping.lower)
            )
        for mapping in self._split_mappings:
            signed = (
                state.channel(mapping.positive_channel)
                - state.channel(mapping.negative_channel)
            )
            signed = max(-1.0, min(1.0, signed))
            scale = -mapping.lower if signed < 0 else mapping.upper
            targets[mapping.source] = signed * scale
        return targets

    def decode_physical_event_targets(
        self, events: Mapping[str, float]
    ) -> dict[str, float]:
        """Convert normalized physical-only events to mechanism coordinates."""

        targets = {}
        known = {mapping.event for mapping in self._physical_event_mappings}
        unknown = tuple(name for name in events if name not in known)
        if unknown:
            raise StateValidationError(f"unknown physical events: {unknown!r}")
        for mapping in self._physical_event_mappings:
            value = events.get(mapping.event, 0.0)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise StateValidationError(
                    f"physical event {mapping.event!r} must be in [0, 1]"
                )
            targets[mapping.source] = (
                mapping.lower + float(value) * (mapping.upper - mapping.lower)
            )
        return targets
