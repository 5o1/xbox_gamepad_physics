"""K2/K3 and N2/N3: actual shape counts, filtering, timing and external probes."""
import json
import time

from .drive_reach import internal_contact_pairs


def run(cfg, ctx):
    import numpy as np
    import sapien
    from xbox_gamepad_physics.resources import resource_path
    from xbox_gamepad_physics.robotwin import load_into_scene
    from xbox_gamepad_physics.state import XBOX_ONE_S_CHANNELS
    gamepad, scene = ctx.gamepad, ctx.scene
    variant = cfg["gamepad"]["collision"]
    collision = json.loads(resource_path("robotwin", cfg["profile"], "collision/manifest.json").read_text())
    counts = {}
    for link in gamepad.articulation.get_links():
        record = collision["links"][link.name]
        expected = record["hull_count"] if variant == "coacd" else len(record["sdf"])
        groups = [list(shape.get_collision_groups()) for shape in link.get_collision_shapes()]
        counts[link.name] = {"expected": expected, "actual": len(groups), "groups": groups}
    shape_counts_ok = all(r["expected"] == r["actual"] for r in counts.values())
    max_internal = 0
    start = time.perf_counter()
    for _ in range(1000):
        scene.step()
        max_internal = max(max_internal, internal_contact_pairs(scene, gamepad.articulation))
    elapsed = time.perf_counter() - start
    probes = {}
    # Probe only one target in each new scene; keep the original scene for timing.
    for component in ("shell", "a", "dpad"):
        probe_scene = sapien.Scene()
        probe_scene.set_timestep(cfg["scene"]["timestep"])
        loaded = load_into_scene(probe_scene, sapien.Pose(), True, attach_visual=False, collision=variant)
        record = collision["links"]
        relative = next(f for r in record.values() for f in r["sdf"] if f.endswith(f"/{component}_0.obj"))
        import trimesh
        mesh = trimesh.load(resource_path("robotwin", cfg["profile"], relative), process=False)
        if component == "shell":
            # Left grip contact point, from meshbase: highest triangle near x=-45 mm,y=-30 mm.
            root_vertices = np.asarray(mesh.vertices)
            candidates = root_vertices[(abs(root_vertices[:, 0] + 0.045) < 0.015) & (abs(root_vertices[:, 1] + 0.03) < 0.015)]
            point = candidates[np.argmax(candidates[:, 2])]
        else:
            control_link = next(link for link in loaded.articulation.get_links()
                                if relative in record[link.name]["sdf"])
            transform = control_link.pose.to_transformation_matrix()
            root_vertices = np.asarray(mesh.vertices) @ transform[:3, :3].T + transform[:3, 3]
            point = root_vertices[np.argmax(root_vertices[:, 2])]
        builder = probe_scene.create_actor_builder()
        builder.add_box_collision(half_size=[0.002, 0.002, 0.002], density=1000)
        builder.set_initial_pose(sapien.Pose(p=point + [0, 0, 0.003]))
        probe = builder.build(name=f"probe_{component}").find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)
        for shape in probe.get_collision_shapes():
            shape.set_contact_offset(0.0002)
            shape.set_rest_offset(0)
        touched, total, max_pairs = set(), 0, 0
        peaks = {name: 0.0 for name in XBOX_ONE_S_CHANNELS}
        links = set(loaded.articulation.get_links())
        for _ in range(240):
            probe.add_force_at_point([0, 0, -0.1], probe.pose.p)
            probe_scene.step()
            max_pairs = max(max_pairs, internal_contact_pairs(probe_scene, loaded.articulation))
            for contact in probe_scene.get_contacts():
                if probe in contact.bodies:
                    for body in contact.bodies:
                        if body in links:
                            touched.add(body.name)
                            total += 1
            state = loaded.gamepad_state()
            for name in peaks:
                peaks[name] = max(peaks[name], abs(state.channel(name)))
        probes[component] = {"contact_pairs_over_steps": total, "touched_links": sorted(touched),
                             "signal_peak": peaks, "max_internal_contact_pairs": max_pairs,
                             "contact_offset_m": 0.0002, "point_m": point.tolist()}
    start = time.perf_counter()
    second_scene = sapien.Scene()
    second = load_into_scene(second_scene, sapien.Pose(), True, attach_visual=False, collision=variant)
    second_time = time.perf_counter() - start
    groups_ok = all(g[2] & 0x80000000 and g[3] == 0x5842 for r in counts.values() for g in r["groups"])
    return {"collision": variant, "shape_counts": counts, "shape_counts_ok": shape_counts_ok,
            "groups_ok": groups_ok, "max_internal_contact_pairs": max_internal,
            "first_load_seconds": ctx.load_seconds, "second_load_seconds": second_time,
            "1000_steps_seconds_including_contact_readback": elapsed, "probes": probes,
            "passed": shape_counts_ok and groups_ok and max_internal == 0}
