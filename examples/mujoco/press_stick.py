"""Apply and release a native load on a passive stick click; no target writes."""
from __future__ import annotations

import argparse
import json
import math


def press_and_release(*, resource_root, side="left", force_n=8.14,
                      hold_s=0.5, release_s=0.5):
    import mujoco
    import numpy as np
    from xbox_gamepad_physics.mujoco import load_standalone

    scene = load_standalone(resource_root=resource_root, fixed_root=True,
                            attach_visual=False)
    model, data, pad = scene.model, scene.data, scene.gamepad
    body = model.body(side + "_stick").id
    root = model.body("controller_body").id
    click = side + "_stick_click"
    snapshots = []
    for phase, load, seconds in (("loaded", force_n, hold_s),
                                 ("released", 0.0, release_s)):
        for _ in range(max(1, math.ceil(seconds / model.opt.timestep))):
            data.qfrc_applied[:] = 0.0
            inward = -data.xmat[root].reshape(3, 3)[:, 2]
            # xipos is the moving stick body's actual world COM. mj_applyFT
            # computes its generalized load; native joint springs stay active.
            mujoco.mj_applyFT(model, data, load * inward, np.zeros(3),
                             data.xipos[body], body, data.qfrc_applied)
            scene.step()
            mujoco.mj_forward(model, data)
        snapshots.append({"phase": phase, "applied_force_n": load,
                          "click_position_m": pad.joint_position(click),
                          "signal": pad.gamepad_state().channel(side + "_stick"),
                          "simulation_time_s": float(data.time)})
    return snapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-root", required=True)
    parser.add_argument("--side", choices=("left", "right"), default="left")
    parser.add_argument("--force-n", type=float, default=8.14)
    parser.add_argument("--hold-s", type=float, default=0.5)
    parser.add_argument("--release-s", type=float, default=0.5)
    args = parser.parse_args()
    if not all(math.isfinite(v) and v >= 0 for v in
               (args.force_n, args.hold_s, args.release_s)):
        parser.error("force and durations must be finite and nonnegative")
    print(json.dumps(press_and_release(resource_root=args.resource_root,
        side=args.side, force_n=args.force_n, hold_s=args.hold_s,
        release_s=args.release_s), indent=2))


if __name__ == "__main__":
    main()
