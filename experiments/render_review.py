"""Render one RoboTwin RT review frame and save simulated control state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .scene import create_camera, take_picture

if TYPE_CHECKING:
    from .runner import RunContext


def run(cfg: dict, ctx: RunContext) -> dict:
    camera = create_camera(ctx.scene, cfg["params"]["camera"])
    for _ in range(cfg["params"]["steps"]):
        ctx.scene.step()

    # Read signals only from simulated articulation state.
    state = ctx.gamepad.gamepad_state()
    take_picture(ctx.scene, camera, ctx.output_dir / "frame.png")
    result = {
        "layout_id": state.layout_id,
        "values": list(state.values),
        "available_mask": list(state.available_mask),
        "task_mask": list(state.task_mask),
        "device_id": state.device_id,
        "qpos": ctx.gamepad.joint_positions(),
    }
    (ctx.output_dir / "state.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8",
    )
    return result
