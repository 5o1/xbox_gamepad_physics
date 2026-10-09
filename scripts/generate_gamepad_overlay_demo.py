"""Generate a deterministic left-stick circle trace for the overlay adapter."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xbox_gamepad_physics.controller import (  # noqa: E402
    AxisSignalMapping,
    GamepadSignalController,
    RadialSignalGroup,
)
from xbox_gamepad_physics.resources import load_json_resource  # noqa: E402


DEFAULT_OUTPUT = ROOT / "build" / "experiments" / "gamepad_overlay_left_stick_circle" / "trace.json"


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _mechanism_coordinate(signal: float, lower: float, upper: float) -> float:
    return signal * (-lower if signal < 0 else upper)


def _controller_from_manifest() -> tuple[GamepadSignalController, dict[str, AxisSignalMapping]]:
    manifest = load_json_resource("robotwin", "left_stick")
    raw_mapping = manifest["state_mapping"]
    mappings = tuple(
        AxisSignalMapping(
            channel=item["channel"],
            source=item["joint"],
            lower=float(item["lower"]),
            upper=float(item["upper"]),
        )
        for item in raw_mapping["axes"]
    )
    groups = tuple(
        RadialSignalGroup(tuple(item["channels"]), float(item["radius"]))
        for item in raw_mapping["radial_groups"]
    )
    return GamepadSignalController.xbox_one_s(mappings, groups), {
        item.channel: item for item in mappings
    }


def build_trace(fps: int = 30) -> dict:
    if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0:
        raise ValueError("fps must be a positive integer")

    controller, mapping_by_channel = _controller_from_manifest()
    phase_lengths = {
        "neutral": round(0.5 * fps),
        "engage": round(0.6 * fps),
        "circle": round(4.0 * fps),
        "release": round(0.6 * fps),
        "settled": round(0.5 * fps),
    }
    left_x = mapping_by_channel["left_x"]
    left_y = mapping_by_channel["left_y"]
    samples: list[tuple[str, float | None, float]] = []
    samples.extend(("neutral", None, 0.0) for _ in range(phase_lengths["neutral"]))
    for index in range(phase_lengths["engage"]):
        denominator = max(1, phase_lengths["engage"] - 1)
        samples.append(("engage", 0.0, _smoothstep(index / denominator)))
    for index in range(phase_lengths["circle"]):
        denominator = max(1, phase_lengths["circle"] - 1)
        samples.append(("circle", 2.0 * math.pi * index / denominator, 1.0))
    for index in range(phase_lengths["release"]):
        denominator = max(1, phase_lengths["release"] - 1)
        samples.append(("release", 2.0 * math.pi, 1.0 - _smoothstep(index / denominator)))
    samples.extend(("settled", None, 0.0) for _ in range(phase_lengths["settled"]))

    frames = []
    maximum_radius_error = 0.0
    for frame_index, (phase, theta, amplitude) in enumerate(samples):
        signal_x = amplitude * (math.cos(theta) if theta is not None else 0.0)
        # Negative screen Y makes positive mathematical angles turn counter-clockwise.
        signal_y = amplitude * (-math.sin(theta) if theta is not None else 0.0)
        qx = _mechanism_coordinate(signal_x, left_x.lower, left_x.upper)
        qy = _mechanism_coordinate(signal_y, left_y.lower, left_y.upper)
        state = controller.encode(
            {left_x.source: qx, left_y.source: qy},
            task_channels=("left_x", "left_y"),
        )
        output_radius = math.hypot(
            state.channel("left_x"), state.channel("left_y")
        )
        maximum_radius_error = max(maximum_radius_error, abs(output_radius - amplitude))
        frames.append(
            {
                "layout_id": state.layout_id,
                "values": list(state.values),
                "available_mask": list(state.available_mask),
                "task_mask": list(state.task_mask),
                "device_id": state.device_id,
                "telemetry": {
                    "frame_index": frame_index,
                    "phase": phase,
                    "theta_deg": None if theta is None else math.degrees(theta) % 360.0,
                    "left_stick_x_rad": qx,
                    "left_stick_y_rad": qy,
                },
            }
        )

    return {
        "schema_version": 1,
        "demo": "left_stick_unit_circle",
        "source_profile": "robotwin/left_stick",
        "fps": fps,
        "frame_count": len(frames),
        "duration_seconds": len(frames) / fps,
        "maximum_radius_error": maximum_radius_error,
        "frames": frames,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    trace = build_trace(args.fps)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(trace, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "frames": trace["frame_count"],
                "fps": trace["fps"],
                "duration_seconds": trace["duration_seconds"],
                "maximum_radius_error": trace["maximum_radius_error"],
            }
        )
    )


if __name__ == "__main__":
    main()
