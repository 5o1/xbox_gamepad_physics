"""Build an index for the full-controls user review videos."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "build" / "experiments" / "full_controls_user_review"
GROUPS = (
    "sticks",
    "face_buttons",
    "center_buttons",
    "shoulders_triggers",
    "dpad",
    "concurrent",
)


def video_record(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = json.loads(result.stdout)
    stream = probe["streams"][0]
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": int(probe["format"]["size"]),
        "duration_seconds": float(probe["format"]["duration"]),
        "resolution": [int(stream["width"]), int(stream["height"])],
        "fps": stream["r_frame_rate"],
        "frames": int(stream["nb_frames"]),
    }


def trace_record(path: Path) -> dict:
    trace = json.loads(path.read_text(encoding="utf-8"))
    record = {
        "path": str(path.relative_to(ROOT)),
        "frames": trace["frame_count"],
        "stimulus": trace["stimulus"],
        "signal_source": trace["signal_source"],
    }
    for field in (
        "physics_hz",
        "contact_video_frames",
        "peak_abs_left_x",
        "final_left_x",
    ):
        if field in trace:
            record[field] = trace[field]
    return record


def main() -> None:
    groups = {}
    for group in GROUPS:
        groups[group] = {
            "comparison_video": video_record(
                RESULTS / "comparison" / f"{group}_robotwin_vs_mujoco.mp4"
            ),
            "robotwin": {
                "video": video_record(
                    RESULTS
                    / "robotwin"
                    / group
                    / f"robotwin_{group}_review.mp4"
                ),
                "trace": trace_record(
                    RESULTS / "robotwin" / group / "observed_trace.json"
                ),
            },
            "mujoco": {
                "video": video_record(
                    RESULTS / "mujoco" / group / f"mujoco_{group}_review.mp4"
                ),
                "trace": trace_record(
                    RESULTS / "mujoco" / group / "observed_trace.json"
                ),
            },
        }

    contact = {
        "comparison_video": video_record(
            RESULTS / "comparison" / "contact_robotwin_vs_mujoco.mp4"
        ),
        "robotwin": {
            "video": video_record(
                RESULTS
                / "robotwin"
                / "contact"
                / "robotwin_left_stick_contact_review.mp4"
            ),
            "trace": trace_record(
                RESULTS / "robotwin" / "contact" / "observed_trace.json"
            ),
        },
        "mujoco": {
            "video": video_record(
                RESULTS
                / "mujoco"
                / "contact"
                / "mujoco_left_stick_contact_review.mp4"
            ),
            "trace": trace_record(
                RESULTS / "mujoco" / "contact" / "observed_trace.json"
            ),
        },
    }
    manifest = {
        "schema_version": 1,
        "status": "materials_ready_pending_user_review",
        "profile": "full_controls_estimated_v0",
        "acceptance_decision_recorded": False,
        "visualization": {
            "video_fps": 12,
            "simulation_video_resolution": [1280, 720],
            "comparison_video_resolution": [1920, 540],
            "overlay": "vendored sevaht/gamepad-overlay driven by each backend qpos readback trace",
            "robotwin": {
                "renderer": "RoboTwin RT + OIDN",
                "samples_per_pixel": 8,
                "gpu_index": 3,
            },
            "mujoco": {
                "version": "3.15.0",
                "renderer": "Filament Vulkan with opacity-role patch",
                "gpu_index": 3,
                "gpu_pci": "0000:ca:00.0",
                "gpu_uuid": "GPU_UUID",
            },
        },
        "groups": groups,
        "physical_contact": contact,
        "requires_target_hardware": [
            "real Xbox One S input driving the simulated articulation",
            "force/travel/angle measurements listed in docs/pending_user_review.md",
        ],
        "requires_live_user_session": [
            "mouse-driven full-control interaction recording",
            "owner acceptance decisions for every video group",
        ],
        "source_scripts": [
            "scripts/render_robotwin_full_controls_review.py",
            "scripts/render_mujoco_full_controls_review.py",
            "scripts/render_robotwin_contact_review.py",
            "scripts/render_mujoco_contact_review.py",
            "scripts/capture_gamepad_overlay_demo.mjs",
        ],
    }
    (RESULTS / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"groups": len(groups), "contact": True}))


if __name__ == "__main__":
    main()
