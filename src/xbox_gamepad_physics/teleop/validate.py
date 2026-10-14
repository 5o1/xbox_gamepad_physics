"""Headless, ordered phase-1 acceptance experiments; stop on a failed key gate."""

from __future__ import annotations

import argparse
import copy
import json
from contextlib import closing
from pathlib import Path

from .gripper import ASSET_URDF, JOINTS, LINKS, derive_urdf, parse_builder
from .session import pose_data
from .record import iter_records


def pose_error(a, b):
    import numpy as np
    # atan2 avoids losing tiny rotations to acos rounding near identity.
    from .session import quat_multiply
    q = quat_multiply(a[3:], (b[3], *(-np.asarray(b[4:]))))
    return float(np.linalg.norm(np.asarray(a[:3])-b[:3])), float(2*np.arctan2(np.linalg.norm(q[1:]), abs(q[0])))


def k1(cfg, output):
    import numpy as np
    from xbox_gamepad_physics.examples.scene import create_scene
    scene = create_scene(cfg["scene"])
    derived = derive_urdf(cfg["teleop"]["robotwin_root"], output / "derived")
    full = parse_builder(scene, Path(cfg["teleop"]["robotwin_root"])/ASSET_URDF, True, cfg["teleop"]).build()
    part = parse_builder(scene, derived, False, cfg["teleop"]).build()
    full_links = {l.name: l for l in full.get_links()}
    part_links = {l.name: l for l in part.get_links()}
    full_joints = {j.name: j for j in full.get_active_joints()}
    part_joints = {j.name: j for j in part.get_active_joints()}
    rows = []
    for q in ([0., 0.], [0.02, 0.035], [0.04765, 0.04765]):
        full_q = np.zeros(full.dof)
        for i, j in enumerate(full.get_active_joints()):
            if j.name in JOINTS:
                full_q[i] = q[JOINTS.index(j.name)]
        full.set_qpos(full_q)
        part.set_qpos([q[JOINTS.index(j.name)] for j in part.get_active_joints()])
        for name in LINKS:
            reference = full_links[LINKS[0]].pose.inv()*full_links[name].pose
            observed = part_links[LINKS[0]].pose.inv()*part_links[name].pose
            position, angle = pose_error(pose_data(observed), pose_data(reference))
            rows.append({"q_m": q, "link": name, "position_error_m": position, "angle_error_rad": angle})
    joint_rows = {}
    for name in JOINTS:
        a, b = full_joints[name], part_joints[name]
        axis_a = a.get_pose_in_child().to_transformation_matrix()[:3, 0]
        axis_b = b.get_pose_in_child().to_transformation_matrix()[:3, 0]
        joint_rows[name] = {"full_axis": axis_a.tolist(), "derived_axis": axis_b.tolist(),
                            "full_limits": a.get_limits().tolist(), "derived_limits": b.get_limits().tolist(),
                            "axis_match": bool(np.array_equal(axis_a, axis_b)),
                            "limits_match": bool(np.array_equal(a.get_limits(), b.get_limits()))}
    counts = {name: {"full": len(full_links[name].get_collision_shapes()),
                     "derived": len(part_links[name].get_collision_shapes())} for name in LINKS}
    inertial = {name: {"mass_kg": part_links[name].mass, "principal_inertia_kg_m2": part_links[name].inertia.tolist(),
                      "cmass_local_pose": pose_data(part_links[name].cmass_local_pose)} for name in LINKS}
    # Compare reconstructed tensor and COM to unchanged source URDF.
    import xml.etree.ElementTree as ET
    tree = ET.parse(derived)
    for node in tree.findall("link"):
        name = node.get("name")
        origin = node.find("inertial/origin")
        values = node.find("inertial/inertia").attrib
        xx, yy, zz, xy, xz, yz = [float(values[k]) for k in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz")]
        tensor = np.asarray([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]])
        link = part_links[name]
        rotation = link.cmass_local_pose.to_transformation_matrix()[:3, :3]
        reconstructed = rotation @ np.diag(link.inertia) @ rotation.T
        inertial[name]["source_mass_kg"] = float(node.find("inertial/mass").get("value"))
        inertial[name]["tensor_max_error_kg_m2"] = float(np.max(np.abs(tensor-reconstructed)))
        inertial[name]["com_max_error_m"] = float(np.max(np.abs(link.cmass_local_pose.p-
                                               list(map(float, origin.get("xyz").split())))))
    passed = (all(r["position_error_m"] <= 1e-6 and r["angle_error_rad"] <= 1e-6 for r in rows)
              and all(r["axis_match"] and r["limits_match"] for r in joint_rows.values())
              and all(r["full"] == r["derived"] for r in counts.values())
              and all(abs(r["mass_kg"]-r["source_mass_kg"]) < 1e-7 and r["tensor_max_error_kg_m2"] < 1e-10
                      and r["com_max_error_m"] < 1e-7 for r in inertial.values()))
    result = {"passed": passed, "poses": rows, "joints": joint_rows, "shape_counts": counts, "inertial": inertial}
    (output/"K1.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def fixed_root_probe(cfg, output):
    """Read actual fixed-root pose/link/query state before and after a step."""
    import numpy as np
    import sapien
    from xbox_gamepad_physics.examples.scene import create_scene
    scene = create_scene(cfg["scene"])
    path = derive_urdf(cfg["teleop"]["robotwin_root"], output/"derived")
    art = parse_builder(scene, path, True, cfg["teleop"]).build()
    art.set_qpos([.011, .015])
    snapshots = []
    def capture(name):
        from .session import articulation_data
        snapshots.append({"stage": name, "actual": articulation_data(art, True),
                          "root_aabb": art.get_root().compute_global_aabb_tight().tolist()})
    capture("before_setter")
    target = [.02, -.03, .15, .9238795325, 0, 0, .3826834324]
    art.set_root_pose(sapien.Pose(target[:3], target[3:]))
    capture("after_in_scene_setter_before_physics")
    scene.step()
    capture("after_first_physics")
    for _ in range(10):
        scene.step()
    capture("after_eleven_physics_steps")
    errors = [pose_error(s["actual"]["pose"], target) for s in snapshots[1:]]
    result = {"passed": all(p <= 1e-6 and r <= 1e-6 for p, r in errors),
              "root_joint_type": art.get_root().joint.type, "target_pose": target,
              "pose_errors_m_rad": errors, "snapshots": snapshots,
              "removed_from_scene": False, "timestep_s": scene.get_timestep(),
              "aabb_changed_before_physics": bool(not np.array_equal(snapshots[0]["root_aabb"], snapshots[1]["root_aabb"]))}
    (output/"fixed_root_probe.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def transfer_probe(record_path, output):
    """Recreate the recorded prefix and inspect the copy before physics runs."""
    from xbox_gamepad_physics.teleop.replay import read_record
    from .runtime import make_session
    from .session import Command, articulation_data
    header, rows = read_record(record_path)
    index = next(r["step"] for r in rows if r["phase"] == "k2_hold")
    session = make_session(header["config"], output)
    for row in rows[:index]:
        session.step(Command(**row["command"]))
    source = articulation_data(session.rig.main, True)
    def properties(art):
        return {j.name: {"stiffness": j.stiffness, "damping": j.damping,
                        "force_limit": j.force_limit, "mode": j.drive_mode}
                for j in art.get_active_joints()}
    source_properties = properties(session.rig.main)
    session.rig.freeze(index*session.dt)
    copied = articulation_data(session.rig.main, True)
    copy_properties = properties(session.rig.main)
    error = pose_error(source["pose"], copied["pose"])
    result = {"physics_steps_in_prefix": index, "source": source, "copy_before_physics": copied,
              "source_drive_properties": source_properties, "copy_drive_properties": copy_properties,
              "pose_error_m_rad": error, "root_joint_type": session.rig.main.get_root().joint.type,
              "passed": source["joints"] == copied["joints"] and source["drive_targets"] == copied["drive_targets"]
                        and source_properties == copy_properties and error[0] <= 1e-6 and error[1] <= 1e-6,
              "group_audit": session.rig.group_audit()}
    (output/"transfer_probe.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def block_clearance(row, cfg):
    """Lowest cuboid point above the configured horizontal table top."""
    import numpy as np
    import sapien
    fixture = cfg["teleop"]["fixture"]
    p = row["fixtures"]["block"]["pose"]
    rotation = sapien.Pose(p[:3], p[3:]).to_transformation_matrix()[:3, :3]
    lowest = p[2] - float(np.abs(rotation[2]) @ fixture["block_half_size_m"])
    top = fixture["table_pose"][2]+fixture["table_half_size_m"][2]
    return lowest-top


def stability(rows, reference_root, reference_block):
    import sapien
    reference = sapien.Pose(reference_root[:3], reference_root[3:]).inv()*sapien.Pose(reference_block[:3], reference_block[3:])
    slip, angle = 0., 0.
    for row in rows:
        root = row["frozen"]["pose"] if row["frozen"]["active"] else row["main"]["pose"]
        block = row["fixtures"]["block"]["pose"]
        actual = sapien.Pose(root[:3], root[3:]).inv()*sapien.Pose(block[:3], block[3:])
        distance, rotation = pose_error(pose_data(actual), pose_data(reference))
        slip, angle = max(slip, distance), max(angle, rotation)
    return slip, angle


def grip_episode(cfg, output, freeze=False, p0_only=False):
    """P0 prefix is identical in P0 and both K2 conditions, with identical cfg."""
    import numpy as np
    import time
    from .runtime import make_session
    from .session import Command
    output.mkdir(parents=True, exist_ok=True)
    (output/"config.json").write_text(json.dumps(cfg, indent=2)+"\n")
    with (output/"record.jsonl").open("w") as record:
        session = make_session(cfg, output, record)
        dt = session.dt
        trajectory = cfg["teleop"]["grasp_test"]
        rows, first_1000_start, first_1000_wall = [], time.perf_counter(), None
        def step(command, phase):
            nonlocal first_1000_wall
            session.phase = phase
            row = session.step(command)["state"]
            rows.append(row)
            if len(rows) == 1000:
                first_1000_wall = time.perf_counter()-first_1000_start
            return row
        for _ in range(round(trajectory["settle_seconds"]/dt)):
            step(Command(), "settle")
        step(Command(opening=-100), "close")
        for _ in range(round(trajectory["close_seconds"]/dt)):
            step(Command(), "close")
        count = round(trajectory["lift_seconds"]/dt)
        increment = trajectory["lift_m"]/count/cfg["teleop"]["input"]["fine"]["translation_m"]
        for _ in range(count):
            step(Command(translation=(0, 0, increment), fine=True), "lift")
        for _ in range(round(trajectory["settle_hold_seconds"]/dt)):
            step(Command(), "settle_hold")
        reference_root = rows[-1]["main"]["pose"]
        reference_block = rows[-1]["fixtures"]["block"]["pose"]
        stable_rows = [step(Command(), "p0_hold") for _ in range(round(2./dt))]
        slip, angle = stability(stable_rows, reference_root, reference_block)
        clearance = min(block_clearance(r, cfg) for r in stable_rows)
        table_contacts = sum(any("block" in c["bodies"] and "table" in c["bodies"] for c in r["contacts"])
                             for r in stable_rows)
        world_distance = max(pose_error(r["fixtures"]["block"]["pose"], reference_block)[0] for r in stable_rows)
        world_angle = max(pose_error(r["fixtures"]["block"]["pose"], reference_block)[1] for r in stable_rows)
        p0 = {"minimum_bottom_clearance_m": clearance, "hold_seconds": len(stable_rows)*dt,
              "relative_displacement_m": slip, "relative_rotation_rad": angle,
              "world_displacement_m": world_distance, "world_rotation_rad": world_angle,
              "table_contact_steps": table_contacts,
              "passed": bool(clearance >= .03 and table_contacts == 0 and slip <= .002 and angle <= np.deg2rad(2)
                             and world_distance <= .002 and world_angle <= np.deg2rad(2))}
        result = {"P0": p0, "passed": p0["passed"]}
        if p0["passed"] and not p0_only:
            root = rows[-1]["main"]["pose"]
            block = rows[-1]["fixtures"]["block"]["pose"]
            hold = [step(Command(toggle=freeze and i == 0), "k2_hold") for i in range(round(2./dt))]
            resume = [step(Command(toggle=freeze and i == 0), "k2_resume") for i in range(round(.5/dt))]
            slip, angle = stability(hold+resume, root, block)
            jump = max(float(np.linalg.norm(np.asarray(r["main"]["pose"][:3])-root[:3])) for r in resume)
            result.update({"max_relative_displacement_m": slip, "max_relative_rotation_rad": angle,
                           "resume_max_root_displacement_m": jump,
                           "minimum_bottom_clearance_m": min(block_clearance(r, cfg) for r in hold+resume),
                           "passed": bool(slip <= .002 and angle <= np.deg2rad(2) and (not freeze or jump <= .001))})
        result.update({"max_internal_contact_pairs": max(r["gamepad_internal_pairs"] for r in rows),
                       "steps": len(rows), "first_1000_wall_seconds_including_record_io": first_1000_wall,
                       "physics_mean_ms": float(np.mean([r["physics_seconds"] for r in rows])*1000),
                       "physics_p95_ms": float(np.percentile([r["physics_seconds"] for r in rows], 95)*1000)})
        (output/"groups.json").write_text(json.dumps(session.rig.group_audit(), indent=2)+"\n")
    (output/"metrics.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def p0(cfg, output):
    return grip_episode(cfg, output, p0_only=True)


def k2(cfg, output):
    import numpy as np
    result = {"conditions": {}, "thresholds": {"slip_m": .002, "rotation_rad": np.deg2rad(2),
                                                "resume_jump_m": .001}}
    result["thresholds"]["rotation_rad"] = float(np.deg2rad(2))
    for condition in ("continuous", "freeze_restore"):
        summary = grip_episode(cfg, output/condition, freeze=condition == "freeze_restore")
        result["conditions"][condition] = summary
        if not summary["passed"]:
            break
    result["passed"] = all(r["passed"] for r in result["conditions"].values())
    (output/"K2.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def overlap_witness(session):
    """An interior point shared by the actual convex finger and test cuboid."""
    import numpy as np
    from scipy.spatial import ConvexHull
    fixture = session.cfg["fixture"]
    block = session.objects["block"]
    transform = block.pose.to_transformation_matrix()
    half = np.asarray(fixture["block_half_size_m"])
    points = np.asarray([[x,y,z] for x in (-.7, 0, .7) for y in (-.7, 0, .7) for z in (-.7, 0, .7)])*half
    points = points @ transform[:3, :3].T + transform[:3, 3]
    for link in session.rig.secondary.get_links():
        for shape in link.get_collision_shapes():
            t = (link.pose*shape.local_pose).to_transformation_matrix()
            vertices = np.asarray(shape.get_vertices())*shape.get_scale()
            vertices = vertices @ t[:3, :3].T+t[:3, 3]
            planes = ConvexHull(vertices).equations
            distance = points @ planes[:, :3].T+planes[:, 3]
            inside = np.max(distance, axis=1) < -1e-6
            if np.any(inside):
                i = np.flatnonzero(inside)[0]
                return {"link": link.name, "point_world_m": points[i].tolist(),
                        "maximum_signed_plane_distance_m": float(distance[i].max())}
    return None


def k3(cfg, output):
    import numpy as np
    from .runtime import make_session
    from .session import Command, GHOST_GROUP, NORMAL_GROUP, State
    output.mkdir(parents=True, exist_ok=True)
    with (output/"record.jsonl").open("w") as record:
        session = make_session(cfg, output, record)
        rows = []
        def step(command, phase):
            session.phase = phase
            row = session.step(command)["state"]
            rows.append(row)
            return row
        for _ in range(round(.5/session.dt)):
            step(Command(), "settle")
        born = session.index
        step(Command(toggle=True), "ghost_birth")
        step(Command(opening=-100), "ghost_overlap")
        for _ in range(round(.65/session.dt)):
            step(Command(), "ghost_overlap")
        witness = overlap_witness(session)
        blocked = rows[-1]["ghost"] and rows[-1]["ghost_blocked"] and "block" in rows[-1]["geometry_blockers"]
        count = round(1/session.dt)
        for _ in range(count):
            step(Command(translation=(0, .18/count/.001, 0), fine=True), "leave_overlap")
        for _ in range(round(.5/session.dt)):
            step(Command(), "clear_hold")
        restored = rows[-1]["state"] == State.SECONDARY_NORMAL.value
        for _ in range(count):
            step(Command(translation=(0, -.18/count/.001, 0), fine=True), "normal_reapproach")
        for _ in range(round(.5/session.dt)):
            step(Command(), "normal_contact")
        ghost_rows = [r for r in rows if r["ghost"]]
        def secondary_contacts(row):
            return [c for c in row["contacts"] if any(b.startswith("secondary/") for b in c["bodies"])]
        ghost_pairs = sum(len(secondary_contacts(r)) for r in ghost_rows)
        ghost_impulse = sum(float(np.linalg.norm(p["impulse_ns"])) for r in ghost_rows
                            for c in secondary_contacts(r) for p in c["points"])
        normal_contacts = [c for r in rows if r["phase"] in ("normal_reapproach", "normal_contact")
                           for c in secondary_contacts(r) if "block" in c["bodies"]]
        normal_impulse = sum(float(np.linalg.norm(p["impulse_ns"])) for c in normal_contacts for p in c["points"])
        first_normal = next((r["step"] for r in rows if r["state"] == State.SECONDARY_NORMAL.value), None)
        groups_ok = all(all(tuple(g) == (GHOST_GROUP if r["ghost"] else NORMAL_GROUP)
                           for groups in r["gripper_collision_groups"]["secondary"].values() for g in groups)
                        for r in rows[born:])
        result = {"ghost_contact_pairs": ghost_pairs, "ghost_impulse_sum_ns": ghost_impulse,
                  "overlap_witness": witness, "blocked_after_minimum": bool(blocked),
                  "normal_after_leaving": restored, "birth_step": born, "first_normal_step": first_normal,
                  "ghost_duration_s": (first_normal-born)*session.dt if first_normal is not None else None,
                  "normal_block_contact_pairs": len(normal_contacts), "normal_block_impulse_sum_ns": normal_impulse,
                  "actual_groups_match": groups_ok, "steps": len(rows),
                  "max_internal_contact_pairs": max(r["gamepad_internal_pairs"] for r in rows),
                  "passed": ghost_pairs == 0 and ghost_impulse == 0 and blocked and witness is not None
                            and restored and len(normal_contacts) > 0 and normal_impulse > 0 and groups_ok}
    (output/"K3.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def k4(record_path, output):
    from xbox_gamepad_physics.teleop.replay import replay, read_record, step_difference
    output.mkdir(parents=True, exist_ok=True)
    first = replay(record_path, output/"first")
    second = replay(record_path, output/"second")
    _, a = read_record(output/"first/replay.jsonl")
    _, b = read_record(output/"second/replay.jsonl")
    divergence = None
    maxima = [0., 0.]
    signals_equal = True
    with (output/"between_replays.jsonl").open("w") as stream:
        for expected, actual in zip(a, b):
            row = step_difference(expected, actual)
            stream.write(json.dumps(row)+"\n")
            maxima[0] = max(maxima[0], row["pose_max_abs"])
            maxima[1] = max(maxima[1], row["joint_max_abs"])
            signals_equal &= row["signals_equal"]
            if not row["passed"] and divergence is None:
                divergence = row
    result = {"passed": first["passed"] and second["passed"] and divergence is None and len(a) == len(b),
              "versus_record": [first, second], "between_replays_first_divergence": divergence,
              "between_replays_max_pose_abs": maxima[0], "between_replays_max_joint_abs": maxima[1],
              "between_replays_signals_equal": signals_equal, "steps_per_replay": len(a)}
    (output/"K4.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def collision_vertices(link):
    import numpy as np
    vertices = []
    for shape in link.get_collision_shapes():
        t = (link.pose*shape.local_pose).to_transformation_matrix()
        points = np.asarray(shape.get_vertices())*shape.get_scale()
        vertices.append(points @ t[:3, :3].T+t[:3, 3])
    return np.vstack(vertices)


def n1(cfg, output):
    """One finite-PD A-button press with an original collision finger tip."""
    import numpy as np
    from .runtime import make_session
    from .session import Command
    episode = copy.deepcopy(cfg)
    test = cfg["teleop"]["a_press_test"]
    episode["teleop"]["fixture"]["include_block"] = False
    episode["teleop"]["initial_pose"] = [.4, 0, .4, 2**-.5, 0, 2**-.5, 0]
    episode["teleop"]["initial_opening_m"] = episode["teleop"]["input"]["open_target_m"]
    # Geometry-only setup; actual run starts freshly at the computed pose.
    geometry = make_session(episode, output/"geometry")
    a = next(link for link in geometry.gamepad.articulation.get_links() if link.name == "a")
    vertices = collision_vertices(a)
    top = vertices[vertices[:, 2] >= vertices[:, 2].max()-.0002].mean(axis=0)
    finger = next(link for link in geometry.rig.main.get_links() if link.name == "fl_link7")
    tip_vertices = collision_vertices(finger)
    tip = tip_vertices[tip_vertices[:, 2] <= tip_vertices[:, 2].min()+.0002].mean(axis=0)
    offset = tip-geometry.rig.main.get_root_pose().p
    position = top+np.asarray([0,0,test["initial_clearance_m"]])-offset
    episode["teleop"]["initial_pose"][:3] = position.tolist()
    del geometry
    output.mkdir(parents=True, exist_ok=True)
    (output/"config.json").write_text(json.dumps(episode, indent=2)+"\n")
    with (output/"record.jsonl").open("w") as record:
        session = make_session(episode, output, record)
        rows = []
        def step(command, phase):
            session.phase = phase
            row = session.step(command)["state"]
            rows.append(row)
        for _ in range(round(test["settle_seconds"]/session.dt)):
            step(Command(), "settle")
        count = round(test["approach_seconds"]/session.dt)
        increment = test["travel_m"]/count/.001
        for _ in range(count):
            step(Command(translation=(0,0,-increment), fine=True), "press_a")
        for _ in range(round(test["hold_seconds"]/session.dt)):
            step(Command(), "hold_a")
        for _ in range(count):
            step(Command(translation=(0,0,increment), fine=True), "release_a")
        peaks = {channel: max(abs(r["signals"][channel]) for r in rows) for channel in rows[0]["signals"]}
        gamepad_bodies = {link.name for link in session.gamepad.articulation.get_links()}
        contacts = [c for r in rows for c in r["contacts"] if any(b.startswith("main/") for b in c["bodies"])
                    and any(b in gamepad_bodies for b in c["bodies"])]
        points = [p for c in contacts for p in c["points"]]
        result = {"noncritical": True, "a_peak": peaks["south"], "a_pressed": peaks["south"] >= test["pressed_threshold"],
                  "pressed_threshold": test["pressed_threshold"], "all_21_channel_peaks": peaks,
                  "other_channels_at_threshold": [k for k,v in peaks.items() if k != "south" and v >= test["pressed_threshold"]],
                  "max_contact_penetration_m": max((max(0.,-p["separation_m"]) for p in points), default=0.),
                  "contacted_links": sorted({b for c in contacts for b in c["bodies"] if b in gamepad_bodies}),
                  "button_top_world_m": top.tolist(), "tip_offset_world_m": offset.tolist(),
                  "steps": len(rows), "max_internal_contact_pairs": max(r["gamepad_internal_pairs"] for r in rows)}
    (output/"N1.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def k5(record_paths, output):
    """Scan every recorded physics step, including both command replays."""
    from .session import GHOST_GROUP, NORMAL_GROUP
    results = []
    for path in record_paths:
        maximum, steps, groups_ok = 0, 0, True
        with closing(iter_records(path)) as stream:
            header = next(stream)
            gamepad_groups = [g for name, g in header["group_audit"]["external"] if name not in ("table", "block")]
            groups_ok &= all(g[2] & 0x80000000 and g[3] == 0x5842 for g in gamepad_groups)
            for row in stream:
                maximum = max(maximum, row["gamepad_internal_pairs"])
                steps += 1
                expected = {"main": NORMAL_GROUP,
                            "secondary": GHOST_GROUP if row["ghost"] or not row["secondary"]["active"] else NORMAL_GROUP}
                groups_ok &= all(tuple(g) == expected[role] for role in expected
                                 for groups in row["gripper_collision_groups"][role].values() for g in groups)
        results.append({"record": str(path), "steps": steps, "max_internal_contact_pairs": maximum,
                        "groups_match": groups_ok})
    result = {"passed": all(r["max_internal_contact_pairs"] == 0 and r["groups_match"] for r in results),
              "total_steps": sum(r["steps"] for r in results), "records": results}
    output.mkdir(parents=True, exist_ok=True)
    (output/"K5.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gate", choices=["K1", "FIXED_ROOT", "TRANSFER", "P0", "K2", "K3", "K4", "K5", "N1"], default="K1")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--records", nargs="+", type=Path)
    args = parser.parse_args()
    from xbox_gamepad_physics.examples.runner import load_config
    from .site import resolve_config
    cfg = resolve_config(load_config(args.config))
    args.output.mkdir(parents=True, exist_ok=True)
    if args.gate == "K5":
        if not args.records:
            parser.error("K5 requires --records")
        result = k5(args.records, args.output)
    elif args.gate in ("TRANSFER", "K4"):
        if args.record is None:
            parser.error(f"{args.gate} requires --record")
        result = {"TRANSFER": transfer_probe, "K4": k4}[args.gate](args.record, args.output)
    else:
        result = {"K1": k1, "FIXED_ROOT": fixed_root_probe, "P0": p0, "K2": k2, "K3": k3, "N1": n1}[args.gate](cfg, args.output)
    print(json.dumps(result))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
