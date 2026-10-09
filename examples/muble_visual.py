"""Apply one MuBlE pose-trace frame inside the approved Blender scene.

Run with Blender's Python. MuBlE environment composition remains external to
this adapter; append or link the desired MuBlE desk and lights before saving.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from xbox_gamepad_physics.muble import BlenderPoseBridge, open_approved_scene


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-blend", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--save", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])

    open_approved_scene(args.approved_blend)
    trace = json.loads(args.trace.resolve(strict=True).read_text(encoding="utf-8"))
    bridge = BlenderPoseBridge.from_current_scene(trace)
    bridge.apply_frame(args.frame)

    import bpy

    bpy.context.view_layer.update()
    if args.save is not None:
        destination = args.save.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(destination))


if __name__ == "__main__":
    main()
