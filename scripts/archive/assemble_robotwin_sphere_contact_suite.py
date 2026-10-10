#!/usr/bin/env python3
"""Capture qpos traces in the SVG overlay, compose clips, and concatenate them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

import cv2
import numpy as np

from render_robotwin_sphere_contact_suite import CONTACT_CASES


ROOT = Path(__file__).resolve().parents[2]


def wait_http(url: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"service did not become ready: {url}")


def composite(simulation: Path, overlay: Path, output: Path) -> None:
    base = cv2.imread(str(simulation), cv2.IMREAD_COLOR)
    layer = cv2.imread(str(overlay), cv2.IMREAD_UNCHANGED)
    if base is None or layer is None or layer.shape[2] != 4:
        raise RuntimeError(f"invalid frame pair: {simulation}, {overlay}")
    target_width = min(330, base.shape[1] // 4)
    target_height = round(layer.shape[0] * target_width / layer.shape[1])
    layer = cv2.resize(layer, (target_width, target_height), interpolation=cv2.INTER_AREA)
    x = base.shape[1] - target_width - 18
    y = base.shape[0] - target_height - 14
    alpha = layer[..., 3:4].astype(np.float32) / 255.0 * 0.72
    base_region = base[y:y + target_height, x:x + target_width].astype(np.float32)
    color = layer[..., :3].astype(np.float32)
    base[y:y + target_height, x:x + target_width] = np.rint(
        color * alpha + base_region * (1.0 - alpha)
    ).astype(np.uint8)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), base):
        raise RuntimeError(f"could not write {output}")


def encode_frames(ffmpeg: str, pattern: Path, fps: int, output: Path) -> None:
    subprocess.run(
        [
            ffmpeg, "-y", "-framerate", str(fps), "-i", str(pattern),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def video_probe(ffprobe: str, path: Path) -> dict:
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
            "-show_entries", "format=duration,size", "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    record = json.loads(result.stdout)
    stream = record["streams"][0]
    return {
        "path": str(path),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": stream["r_frame_rate"],
        "frames": int(stream["nb_frames"]),
        "duration_seconds": float(record["format"]["duration"]),
        "bytes": int(record["format"]["size"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--tests", nargs="+", choices=tuple(case.key for case in CONTACT_CASES), default=tuple(case.key for case in CONTACT_CASES))
    parser.add_argument("--modes", nargs="+", choices=("fixed", "free"), default=("fixed", "free"))
    parser.add_argument("--http-port", type=int, default=8870)
    parser.add_argument("--cdp-port", type=int, default=9331)
    args = parser.parse_args()

    suite = args.suite_root.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    viewer_url = f"http://127.0.0.1:{args.http_port}/viewer/gamepad_overlay/index.html"
    cdp_url = f"http://127.0.0.1:{args.cdp_port}"
    server = subprocess.Popen(
        ["python3", "-m", "http.server", str(args.http_port), "--bind", "127.0.0.1", "--directory", str(ROOT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    chrome_profile = output / "chrome-profile"
    chrome = subprocess.Popen(
        [
            str(args.chrome), "--headless", "--no-sandbox", "--disable-dev-shm-usage",
            f"--remote-debugging-port={args.cdp_port}", f"--user-data-dir={chrome_profile}",
            "--window-size=480,270", "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    records = []
    ordered_videos = []
    try:
        wait_http(viewer_url)
        wait_http(f"{cdp_url}/json/version")
        selected = {case.key: case for case in CONTACT_CASES}
        for case_key in args.tests:
            case = selected[case_key]
            for mode in args.modes:
                segment = suite / mode / case.key
                trace_path = segment / "observed_trace.json"
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                if trace["signal_source"] != "sapien_articulation_qpos_readback_after_every_physics_tick":
                    raise RuntimeError(f"untrusted signal source in {trace_path}")
                if trace["commanded_gamepad_state_during_recording"] is not False:
                    raise RuntimeError(f"commanded state contaminated {trace_path}")
                overlay_frames = segment / "overlay_frames"
                subprocess.run(
                    [
                        args.node, str(ROOT / "scripts/archive/capture_gamepad_overlay_demo.mjs"),
                        viewer_url, cdp_url, str(trace_path), str(overlay_frames),
                        "480", "270", "transparent",
                    ],
                    cwd=ROOT,
                    check=True,
                )
                composed_frames = segment / "composed_frames"
                for frame_index in range(trace["frame_count"]):
                    name = f"frame_{frame_index:04d}.png"
                    composite(segment / "frames" / name, overlay_frames / name, composed_frames / name)
                video = segment / f"{mode}_{case.key}.mp4"
                encode_frames(args.ffmpeg, composed_frames / "frame_%04d.png", args.fps, video)
                ordered_videos.append(video)
                records.append(
                    {
                        "mode": mode,
                        "test_key": case.key,
                        "test_label": case.label,
                        "channel": case.channel,
                        "contact_video_frames": trace["contact_video_frames"],
                        "peak_abs_signal": trace["peak_abs_signal"],
                        "peak_root_displacement_m": trace["peak_root_displacement_m"],
                        "video": video_probe(args.ffprobe, video),
                    }
                )
    finally:
        chrome.terminate()
        server.terminate()
        chrome.wait(timeout=15)
        server.wait(timeout=15)

    concat_file = output / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in ordered_videos),
        encoding="utf-8",
    )
    final_video = output / "robotwin_sphere_contact_fixed_and_free_three_view.mp4"
    subprocess.run(
        [
            args.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", "-movflags", "+faststart", str(final_video),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    manifest = {
        "schema_version": 1,
        "backend": "robotwin_sapien",
        "profile": "full_controls",
        "stimulus": "kinematic_sphere_collision_only",
        "signal_source": "sapien_articulation_qpos_readback_after_every_physics_tick",
        "commanded_gamepad_state_during_recording": False,
        "camera_layout": ["front", "top", "left_oblique"],
        "overlay": "vendored sevaht/gamepad-overlay through canonical qpos trace adapter",
        "segment_order": "each control fixed then free",
        "segments": records,
        "final_video": video_probe(args.ffprobe, final_video),
        "acceptance": "pending_user_review",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"segments": len(records), "final_video": str(final_video), "duration": manifest["final_video"]["duration_seconds"]}))


if __name__ == "__main__":
    main()
