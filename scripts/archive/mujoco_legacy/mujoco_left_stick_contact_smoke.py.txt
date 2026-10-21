"""Push the MuJoCo left stick with a mocap sphere and record numeric response."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--push-steps", type=int, default=240)
    parser.add_argument("--release-steps", type=int, default=480)
    args = parser.parse_args()

    import mujoco
    import numpy as np

    from xbox_gamepad_physics.mujoco import load_scene

    loaded = load_scene(
        profile="full_controls", scene="contact_probe"
    )
    model, data, gamepad = loaded.model, loaded.data, loaded.gamepad
    body = model.body("left_stick_contact_probe")
    mocap_id = int(body.mocapid[0])
    probe_geom_id = int(model.geom("left_stick_contact_probe_geom").id)
    start = np.array([-0.0110353599917, 0.0241336290442, 0.0281238632209])
    end = np.array([-0.0270353599917, 0.0241336290442, 0.0281238632209])
    data.mocap_pos[mocap_id] = start
    mujoco.mj_forward(model, data)

    contact_frames = 0
    peak_abs_left_x = 0.0
    peak_qpos = 0.0
    for index in range(args.push_steps):
        alpha = index / max(1, args.push_steps - 1)
        data.mocap_pos[mocap_id] = start * (1 - alpha) + end * alpha
        mujoco.mj_step(model, data)
        has_probe_contact = any(
            int(contact.geom1) == probe_geom_id or int(contact.geom2) == probe_geom_id
            for contact in data.contact[: data.ncon]
        )
        contact_frames += int(has_probe_contact)
        state = gamepad.gamepad_state()
        peak_abs_left_x = max(peak_abs_left_x, abs(state.channel("left_x")))
        peak_qpos = max(peak_qpos, abs(gamepad.joint_positions()["left_stick_x"]))

    data.mocap_pos[mocap_id] = start
    for _ in range(args.release_steps):
        mujoco.mj_step(model, data)
    final = gamepad.joint_positions()
    result = {
        "mujoco": mujoco.__version__,
        "profile": "full_controls",
        "scene": "contact_probe",
        "contact_frames": contact_frames,
        "peak_abs_left_x": peak_abs_left_x,
        "peak_abs_left_stick_x_rad": peak_qpos,
        "released_left_stick_x_rad": final["left_stick_x"],
        "released_left_stick_y_rad": final["left_stick_y"],
        "finite": all(np.isfinite(value) for value in final.values()),
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
