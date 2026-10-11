"""N1: free-root drops from a 20 mm meshbase gap onto a RoboTwin box tabletop."""
import json


def run(cfg, ctx):
    import numpy as np
    import sapien
    import trimesh
    from xbox_gamepad_physics.resources import resource_path
    from xbox_gamepad_physics.state import XBOX_ONE_S_CHANNELS
    from .drive_reach import internal_contact_pairs
    gamepad, scene = ctx.gamepad, ctx.scene
    root = gamepad.articulation
    collision = json.loads(resource_path("robotwin", cfg["profile"], "collision/manifest.json").read_text())
    geometry = {name: [np.asarray(trimesh.load(resource_path("robotwin", cfg["profile"], f), process=False).vertices)
                       for f in record["sdf"]] for name, record in collision["links"].items()}

    def lowest():
        values = []
        for link in root.get_links():
            t = link.pose.to_transformation_matrix()
            for vertices in geometry[link.name]:
                values.append((vertices @ t[:3, :3].T + t[:3, 3])[:, 2].min())
        return float(min(values))

    table_top = cfg["params"]["table_top_m"]
    thickness = 0.05
    builder = scene.create_actor_builder()
    builder.add_box_collision(half_size=[0.6, 0.35, thickness / 2])
    builder.set_initial_pose(sapien.Pose(p=[0, 0, table_top - thickness / 2]))
    builder.build_static(name="robotwin_tabletop")
    pose = root.get_root_pose()
    p = np.array(pose.p, dtype=float)
    p[2] += table_top + 0.02 - lowest()
    root.set_root_pose(sapien.Pose(p=p, q=pose.q))
    initial_gap = lowest() - table_top
    peaks = {name: 0.0 for name in XBOX_ONE_S_CHANNELS}
    max_internal = 0
    for _ in range(round(3.0 / cfg["scene"]["timestep"])):
        scene.step()
        state = gamepad.gamepad_state()
        for name in peaks:
            peaks[name] = max(peaks[name], abs(state.channel(name)))
        max_internal = max(max_internal, internal_contact_pairs(scene, root))
    speed = float(np.linalg.norm(root.get_root_linear_velocity()))
    gap = lowest() - table_top
    return {"collision": cfg["gamepad"]["collision"], "orientation": cfg["params"]["orientation"],
            "initial_meshbase_gap_m": initial_gap, "duration_s": 3.0,
            "root_height_m": float(root.get_root_pose().p[2]), "final_linear_speed_m_s": speed,
            "final_angular_speed_rad_s": float(np.linalg.norm(root.get_root_angular_velocity())),
            "meshbase_gap_m": gap, "penetration_m": max(0.0, -gap), "signal_peaks": peaks,
            "max_internal_contact_pairs": max_internal,
            "noncritical_passed": speed < 1e-3 and max(0.0, -gap) <= 0.0005}
