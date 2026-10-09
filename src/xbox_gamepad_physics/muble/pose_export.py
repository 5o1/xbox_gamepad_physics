"""Export MuBlE body-pose traces through the public Xbox MuJoCo handle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from xbox_gamepad_physics.mujoco import LoadedScene
from xbox_gamepad_physics.resources import load_json_resource
from xbox_gamepad_physics.state import GamepadState


MUBLE_BODY_POSE_TRACE_SCHEMA = "muble/body-pose-trace-v1"


@dataclass(frozen=True, slots=True)
class PoseCommand:
    """One commanded gamepad state captured after optional physics steps."""

    label: str
    state: GamepadState
    physical_events: Mapping[str, float] = field(default_factory=dict)
    steps: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("pose command label must be a non-empty string")
        if not isinstance(self.state, GamepadState):
            raise TypeError("pose command state must be a GamepadState")
        if isinstance(self.steps, bool) or not isinstance(self.steps, int) or self.steps < 0:
            raise ValueError("pose command steps must be a non-negative integer")


def _scalar_index(value: Any, context: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(value[0])
        except (TypeError, ValueError, IndexError) as error:
            raise ValueError(f"{context} does not expose one integer index") from error


def derive_part_to_body(model: Any) -> dict[str, str]:
    """Derive visual-part ownership from compiled MuJoCo geom/body names.

    The packaged physical MJCF names each render geom ``visual_<part>``. This
    removes the need for a separate MuBlE binding file or RoboTwin metadata.
    """

    manifest = load_json_resource("common", "xbox_one_s", "visual/manifest.json")
    mapping: dict[str, str] = {}
    for part in manifest["parts"]:
        name = part["name"]
        geom_name = f"visual_{name}"
        try:
            geom = model.geom(geom_name)
            body_id = _scalar_index(geom.bodyid, f"MuJoCo geom {geom_name!r}")
            body_name = model.body(body_id).name
        except Exception as error:
            raise ValueError(
                f"compiled MuJoCo model lacks the visual/body binding for {name!r}"
            ) from error
        if not isinstance(body_name, str) or not body_name:
            raise ValueError(f"MuJoCo body for visual part {name!r} has no name")
        mapping[name] = body_name
    if len(mapping) != 16 or len(set(mapping)) < 1:
        raise ValueError("Xbox visual manifest must resolve all sixteen parts")
    return mapping


def _body_pose(data: Any, body_name: str) -> dict[str, list[float]]:
    try:
        body = data.body(body_name)
        position = [float(value) for value in body.xpos]
        quaternion = [float(value) for value in body.xquat]
    except Exception as error:
        raise ValueError(f"MuJoCo data lacks body {body_name!r}") from error
    if len(position) != 3 or len(quaternion) != 4:
        raise ValueError(f"MuJoCo body {body_name!r} returned an invalid pose")
    return {"position": position, "quaternion_wxyz": quaternion}


def export_pose_trace(
    loaded: LoadedScene,
    commands: Iterable[PoseCommand],
) -> dict[str, Any]:
    """Apply canonical gamepad commands and return a MuBlE pose trace.

    The function mutates ``loaded.data``. It uses the packaged
    :class:`MujocoGamepadHandle` for all control writes and derives Blender-part
    ownership from the compiled model itself.
    """

    try:
        import mujoco
    except ModuleNotFoundError as error:
        raise RuntimeError("MuJoCo is required to export a MuBlE pose trace") from error

    records = tuple(commands)
    if not records:
        raise ValueError("at least one pose command is required")
    labels = [record.label for record in records]
    if len(set(labels)) != len(labels):
        raise ValueError("pose command labels must be unique")

    part_to_body = derive_part_to_body(loaded.model)
    body_names = tuple(dict.fromkeys(part_to_body.values()))
    frames = []
    controls = []
    for frame_index, command in enumerate(records):
        loaded.gamepad.set_gamepad_state(command.state)
        known_events = loaded.gamepad.physical_events()
        events = {name: 0.0 for name in known_events}
        events.update({name: float(value) for name, value in command.physical_events.items()})
        loaded.gamepad.set_physical_events(events)
        if command.steps:
            for _ in range(command.steps):
                mujoco.mj_step(loaded.model, loaded.data)
        else:
            mujoco.mj_forward(loaded.model, loaded.data)
        frames.append(
            {
                "frame_index": frame_index,
                "simulation_time": float(loaded.data.time),
                "bodies": {
                    name: _body_pose(loaded.data, name) for name in body_names
                },
            }
        )
        controls.append(
            {
                "frame_index": frame_index,
                "label": command.label,
                "gamepad_state": {
                    "layout_id": command.state.layout_id,
                    "values": list(command.state.values),
                    "available_mask": list(command.state.available_mask),
                    "task_mask": list(command.state.task_mask),
                    "device_id": command.state.device_id,
                },
                "physical_events": events,
                "physics_steps": command.steps,
            }
        )

    return {
        "schema": MUBLE_BODY_POSE_TRACE_SCHEMA,
        "generator": "xbox_gamepad_physics.muble.export_pose_trace",
        "asset": "Xbox One S",
        "profile": loaded.profile,
        "part_to_body": part_to_body,
        "controls": controls,
        "frames": frames,
    }
