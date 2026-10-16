"""Named scalar and batched handle contracts without simulator imports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol
from ...controller import GamepadSignalController
from ...state import GamepadState


@dataclass(frozen=True)
class ResetRequest:
    root_pose: Any = None
    root_twist: Any = None
    joint_positions: Mapping[str, float] | None = None
    joint_velocities: Mapping[str, float] | None = None
    targets: str = "passive"


class GamepadHandle(Protocol):
    asset_id: str
    profile: str
    backend: str
    capabilities: frozenset[str]
    @property
    def joint_names(self) -> tuple[str, ...]: ...
    @property
    def root_fixed(self) -> bool: ...
    def joint_position(self, name: str) -> float: ...
    def joint_positions(self) -> dict[str, float]: ...
    def joint_velocity(self, name: str) -> float: ...
    def set_joint_positions(self, positions: Mapping[str, float]) -> None: ...
    def set_joint_target(self, name: str, target: float) -> None: ...
    def gamepad_state(self, task_channels: Iterable[str] | None = None) -> GamepadState: ...
    def physical_events(self) -> dict[str, float]: ...
    def set_gamepad_state(self, state: GamepadState) -> None: ...
    def set_gamepad_targets(self, state: GamepadState) -> None: ...
    def set_physical_events(self, events: Mapping[str, float]) -> None: ...
    def root_pose(self): ...
    def root_twist(self): ...
    def reset(self, request: ResetRequest) -> None: ...
    def restore_passive_targets(self) -> None: ...


class BatchedGamepadHandle(Protocol):
    num_envs: int
    device: Any
    dtype: Any
    joint_names: tuple[str, ...]
    def select(self, env_id: int) -> GamepadHandle: ...
    def joint_positions(self, env_ids=None, *, copy: bool = True): ...
    def gamepad_state(self, env_ids=None, *, task_mask=None, copy: bool = True): ...
    def set_gamepad_state(self, state, env_ids=None) -> None: ...
    def set_gamepad_targets(self, state, env_ids=None) -> None: ...
    def reset(self, request, env_ids=None) -> None: ...


def validate_env_ids(env_ids, num_envs: int) -> tuple[int, ...]:
    selected = tuple(range(num_envs)) if env_ids is None else tuple(env_ids)
    if any(type(i) is not int or not 0 <= i < num_envs for i in selected):
        raise ValueError("env_ids must contain integer indices in range")
    if len(set(selected)) != len(selected):
        raise ValueError("env_ids must not contain duplicates")
    return selected


class SignalHandleMixin:
    """Reuse only signal operations; native named reads/writes remain adapters."""
    _signal_controller: GamepadSignalController

    def gamepad_state(
        self, task_channels: Iterable[str] | None = None
    ) -> GamepadState:
        """Return the canonical tensor state exposed by this partial asset.

        Availability comes from the mappings actually present in the loaded
        simulator profile.  This prevents an unfinished physical asset from
        reporting unimplemented Xbox controls as valid neutral observations.
        """

        return self._signal_controller.encode(
            self.joint_positions(), task_channels=task_channels
        )

    def physical_events(self) -> dict[str, float]:
        """Return normalized device-management events outside the game tensor."""

        return self._signal_controller.encode_physical_events(self.joint_positions())

    def set_gamepad_state(self, state: GamepadState) -> None:
        """Synchronize articulation qpos from a canonical gamepad state."""

        self.set_joint_positions(self._signal_controller.decode_joint_targets(state))

    def set_gamepad_targets(self, state: GamepadState) -> None:
        """Set named drive targets from a canonical gamepad state."""

        for name, target in self._signal_controller.decode_joint_targets(state).items():
            self.set_joint_target(name, target)

    def set_physical_events(self, events: Mapping[str, float]) -> None:
        """Synchronize physical-only controls such as Pair/Bind."""

        self.set_joint_positions(
            self._signal_controller.decode_physical_event_targets(events)
        )
