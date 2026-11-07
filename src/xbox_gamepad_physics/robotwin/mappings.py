"""Native RoboTwin mappings for approved preload and shaft-angle boundaries."""
from __future__ import annotations

import math


def apply_preload(articulation, scene, preload_by_joint):
    """Add once to existing qf; PhysX retains this load until the caller changes it."""
    offsets = {}
    index = 0
    for joint in articulation.get_active_joints():
        offsets[joint.name] = index
        index += joint.dof
    forces = articulation.get_qf().copy()
    for name, value in preload_by_joint.items():
        forces[offsets[name]] += value
    articulation.set_qf(forces)


def attach_shaft_limits(scene, articulation, motion, policy):
    """Map the common angular boundary to distance or native D6 constraints."""
    import sapien
    import numpy as np
    joints = {joint.name: joint for joint in articulation.get_active_joints()}
    links = {link.name: link for link in articulation.get_links()}
    constraints, records = [], []
    for limit in motion.joint_space_constraints:
        if limit.get("type") != "shaft_tilt_limit":
            continue
        click_name = limit["independent_of"][0]
        parent = joints[click_name].get_child_link()
        child = links[limit["moving_link"]]
        if policy["mechanism"] == "native_d6_cone":
            # +X maps to the shaft's +Z. Approved a2/a3 builds enable both
            # swing limits; translations and twist remain free.
            frame = sapien.Pose(limit["pivot_in_moving_m"], [math.sqrt(.5), 0, -math.sqrt(.5), 0])
            parent_frame = parent.entity_pose.inv() * child.entity_pose * frame
            connection = scene.create_drive(parent, parent_frame, child, frame)
            connection.set_limit_cone(limit["max_angle_rad"], limit["max_angle_rad"], 0, 0)
            constraints.append(connection)
            records.append({"name": limit["id"], "mechanism": "native_d6_cone",
                            "parent": parent.name, "child": child.name,
                            "maximum_angle_rad": limit["max_angle_rad"],
                            "parent_pivot_m": parent_frame.p.tolist(), "child_pivot_m": frame.p.tolist(),
                            "frame_wxyz": frame.q.tolist()})
            continue
        if policy["mechanism"] != "native_distance_upper_bound":
            raise ValueError(f"unsupported RoboTwin shaft limit mechanism: {policy['mechanism']}")
        length = policy["anchor_length_m"]
        # Both tilt frames share a pivot. Convert its neutral world shaft tip
        # into each local frame, so translated/rotated root poses are supported.
        shaft_pose = child.entity_pose
        point = (shaft_pose * sapien.Pose(np.asarray(limit["moving_axis"])*length)).p
        parent_point = (parent.entity_pose.inv()*sapien.Pose(point)).p
        child_point = (child.entity_pose.inv()*sapien.Pose(point)).p
        maximum = 2*length*math.sin(limit["max_angle_rad"]/2)
        connection = scene.create_connection(parent, sapien.Pose(parent_point), child, sapien.Pose(child_point))
        connection.set_limit(policy["minimum_distance_m"], maximum,
                             policy["stiffness_n_per_m"], policy["damping_ns_per_m"])
        constraints.append(connection)
        records.append({"name": limit["id"], "parent": parent.name, "child": child.name,
                        "parent_anchor_m": parent_point.tolist(), "child_anchor_m": child_point.tolist(),
                        "anchor_length_m": length, "maximum_distance_m": maximum})
    return constraints, records

CPU_PRELOAD_NOTICE = (
    "SAPIEN GPU mode currently does not support stick-click preload. "
    "Use a CPU PhysX scene (GPU rendering is supported). CPU loading adds a persistent "
    "-7.4 N native generalized preload to each click DOF. The 10.4 N cap applies only "
    "to the spring drive. A later set_qf overwrite removes preload; compose caller "
    "loads with the existing qf. The loader never initializes or steps a scene."
    " Dimensional joint_friction_params require the approved PhysX5.6.1 port; "
    "legacy coefficient resources remain loadable. native_d6_cone requires the "
    "approved a3 port (validated a2 is also supported); stock/a1 are incompatible. "
    "Full-controls defaults use implicit drive damping and per-articulation64/16. "
    "Damping and spring share the original drive cap; equivalence to an unbounded "
    "linear viscous term applies only before saturation. These are simulation "
    "compatibility settings, not identified hardware friction."
)
