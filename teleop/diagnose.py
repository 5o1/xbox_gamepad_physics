"""Inspect recorded grasp failures; reconstruct missing v1 contact normals."""

import argparse
import csv
import json
from pathlib import Path


def analyze(path, output):
    import numpy as np
    import sapien
    from experiments.teleop_replay import read_record
    from .validate import pose_error
    header, rows = read_record(path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    phases = {}
    with (output/"steps.csv").open("w") as stream, (output/"contact_geometry.jsonl").open("w") as contacts:
        writer = csv.DictWriter(stream, fieldnames=["step", "phase", "finger7_m", "finger8_m", "finger_target_m",
                  "root_position_error_m", "root_angle_error_rad", "force_n", "torque_nm", "force_saturated",
                  "torque_saturated", "block_z_m", "finger_contact_points", "table_contact_points",
                  "mean_abs_normal_y", "max_impulse_ns"])
        writer.writeheader()
        for row in rows:
            phase = row.get("phase") or ("settle" if row["step"] < 125 else "close" if row["step"] < 376
                                         else "lift" if row["step"] < 876 else "hold")
            displacement, angle = pose_error(row["target_pose"], row["main"]["pose"])
            force = float(np.linalg.norm(row["drive"]["force_n"]))
            torque = float(np.linalg.norm(row["drive"]["torque_nm"]))
            points, table = [], []
            for contact in row["contacts"]:
                if "block" not in contact["bodies"]:
                    continue
                if any(b.startswith("main/fl_link7") or b.startswith("main/fl_link8") for b in contact["bodies"]):
                    points.extend(contact["points"])
                    block = row["fixtures"]["block"]["pose"]
                    root = row["main"]["pose"]
                    bp, rp = sapien.Pose(block[:3], block[3:]), sapien.Pose(root[:3], root[3:])
                    contacts.write(json.dumps({"step": row["step"], "phase": phase, "bodies": contact["bodies"],
                           "points": [{**p, "block_local_m": (bp.inv()*sapien.Pose(p["position_m"])).p.tolist(),
                                       "gripper_root_local_m": (rp.inv()*sapien.Pose(p["position_m"])).p.tolist()}
                                      for p in contact["points"]]})+"\n")
                if "table" in contact["bodies"]:
                    table.extend(contact["points"])
            data = {"step": row["step"], "phase": phase, "finger7_m": row["main"]["joints"]["fl_joint7"],
                    "finger8_m": row["main"]["joints"]["fl_joint8"], "finger_target_m": row["finger_target_m"],
                    "root_position_error_m": displacement, "root_angle_error_rad": angle,
                    "force_n": force, "torque_nm": torque,
                    "force_saturated": force >= header["config"]["teleop"]["root_drive"]["force_limit_n"]-1e-6,
                    "torque_saturated": torque >= header["config"]["teleop"]["root_drive"]["torque_limit_nm"]-1e-6,
                    "block_z_m": row["fixtures"]["block"]["pose"][2], "finger_contact_points": len(points),
                    "table_contact_points": len(table),
                    "mean_abs_normal_y": float(np.mean([abs(p["normal_world"][1]) for p in points])) if points else None,
                    "max_impulse_ns": max((float(np.linalg.norm(p["impulse_ns"])) for p in points), default=0)}
            writer.writerow(data)
            phases.setdefault(phase, []).append(data)
    result = {}
    for phase, values in phases.items():
        contact_rows = [r for r in values if r["finger_contact_points"]]
        result[phase] = {"steps": len(values), "contact_steps": len(contact_rows),
                        "last_contact_step": contact_rows[-1]["step"] if contact_rows else None,
                        "force_saturated_steps": sum(r["force_saturated"] for r in values),
                        "torque_saturated_steps": sum(r["torque_saturated"] for r in values),
                        "max_position_error_m": max(r["root_position_error_m"] for r in values),
                        "max_angle_error_degrees": float(np.rad2deg(max(r["root_angle_error_rad"] for r in values))),
                        "max_force_n": max(r["force_n"] for r in values), "max_torque_nm": max(r["torque_nm"] for r in values),
                        "contact_mean_abs_normal_y": float(np.mean([r["mean_abs_normal_y"] for r in contact_rows])) if contact_rows else None}
    (output/"summary.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def reconstruct(path, output):
    from experiments.teleop_replay import read_record, step_difference
    from .runtime import make_session
    from .session import Command
    header, original = read_record(path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    worst, first = 0., None
    with (output/"reconstructed.jsonl").open("w") as stream:
        session = make_session(header["config"], output, stream)
        for expected in original:
            actual = session.step(Command(**expected["command"]))["state"]
            difference = step_difference(expected, actual)
            worst = max(worst, difference["pose_max_abs"], difference["joint_max_abs"])
            if not difference["passed"] and first is None:
                first = difference
    evidence = {"source": str(path), "first_pose_joint_signal_divergence": first, "maximum_abs": worst,
                "note": "v1 did not record normals; these are reconstructed, never inserted into original"}
    (output/"reconstruction_comparison.json").write_text(json.dumps(evidence, indent=2)+"\n")
    return analyze(output/"reconstructed.jsonl", output)


def geometry(cfg, output):
    """Cross sections of the actual cooked convex finger shapes at q=0."""
    import numpy as np
    from scipy.spatial import ConvexHull
    from .runtime import make_session
    session = make_session(cfg, output)
    rows = []
    session.rig.main.set_qpos([0, 0])  # geometry diagnostic, never a grasp step
    for link in session.rig.main.get_links()[1:]:
        for shape in link.get_collision_shapes():
            transform = (session.rig.main.get_root_pose().inv()*link.pose*shape.local_pose).to_transformation_matrix()
            vertices = np.asarray(shape.get_vertices())*shape.get_scale()
            vertices = vertices @ transform[:3, :3].T + transform[:3, 3]
            planes = ConvexHull(vertices).equations
            for x in (.11, .12, .13, .14, .15):
                for z in (-.02, -.01, 0, .01, .02):
                    offset = planes[:, 0]*x + planes[:, 2]*z + planes[:, 3]
                    normal_y = planes[:, 1]
                    low = max((-offset[normal_y < -1e-8]/normal_y[normal_y < -1e-8]), default=-float("inf"))
                    high = min((-offset[normal_y > 1e-8]/normal_y[normal_y > 1e-8]), default=float("inf"))
                    if low <= high and np.all(offset[np.abs(normal_y) <= 1e-8] <= 1e-7):
                        rows.append({"link": link.name, "root_x_m": x, "root_z_m": z,
                                     "minimum_y_m": float(low), "maximum_y_m": float(high)})
    Path(output, "finger_sections.json").write_text(json.dumps(rows, indent=2)+"\n")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reconstruct", action="store_true")
    parser.add_argument("--geometry", action="store_true")
    args = parser.parse_args()
    if args.geometry:
        from experiments.runner import load_config
        print(json.dumps(geometry(load_config(args.record), args.output)))
    else:
        print(json.dumps((reconstruct if args.reconstruct else analyze)(args.record, args.output)))


if __name__ == "__main__":
    main()
