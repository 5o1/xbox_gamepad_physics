"""Three-link aloha-agilex gripper, floating PD and in-place ratchet freeze."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .session import GHOST_GROUP, NORMAL_GROUP, articulation_data, assert_group_available, pose_data

LINKS = ("fl_link6", "fl_link7", "fl_link8")
JOINTS = ("fl_joint7", "fl_joint8")
ASSET_URDF = "assets/embodiments/aloha-agilex/urdf/arx5_description_isaac.urdf"
ASSET_CARD = "https://huggingface.co/datasets/TianxingChen/RoboTwin2.0/blob/3dc3b798668feb99ac61cc9086d84cbcc3d79186/README.md"


def derive_urdf(robotwin_root, output):
    root = Path(robotwin_root)
    source = root / ASSET_URDF
    original = ET.parse(source).getroot()
    derived = ET.Element("robot", name="aloha_agilex_left_gripper")
    derived.append(ET.Comment("Derived from RoboTwin aloha-agilex; MIT dataset card: " + ASSET_CARD))
    for child in original:
        if child.tag == "material" or (child.tag == "link" and child.get("name") in LINKS) or (
                child.tag == "joint" and child.get("name") in JOINTS):
            node = copy.deepcopy(child)
            for mesh in node.findall(".//mesh"):
                mesh.set("filename", str((source.parent / mesh.get("filename")).resolve(strict=True)))
            derived.append(node)
    if {l.get("name") for l in derived.findall("link")} != set(LINKS):
        raise ValueError("source lacks selected gripper links")
    if {j.get("name") for j in derived.findall("joint")} != set(JOINTS):
        raise ValueError("source lacks selected gripper joints")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "left_gripper.urdf"
    ET.indent(derived)
    ET.ElementTree(derived).write(path, encoding="utf-8", xml_declaration=True)
    # Original upstream license is carried alongside, never changed.
    (output / "RoboTwin_LICENSE").write_text((root / "LICENSE").read_text())
    provenance = {"source_urdf": str(source), "asset_card": ASSET_CARD,
                  "license": "MIT; installed archive version unverified; upstream LICENSE copied",
                  "kept_links": list(LINKS), "kept_joints": list(JOINTS),
                  "removed_links": [l.get("name") for l in original.findall("link") if l.get("name") not in LINKS],
                  "removed_joints": [j.get("name") for j in original.findall("joint") if j.get("name") not in JOINTS],
                  "inertial": {l.get("name"): ET.tostring(l.find("inertial"), encoding="unicode")
                               for l in derived.findall("link")}}
    (output / "gripper_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return path


def parse_builder(scene, path, fixed, cfg):
    loader = scene.create_urdf_loader()
    loader.fix_root_link = fixed
    loader.load_multiple_collisions_from_file = False
    material = cfg["material"]
    loader.set_material(material["static_friction"], material["dynamic_friction"], material["restitution"])
    builders, actors, _ = loader.parse(str(path))
    if len(builders) != 1 or actors:
        raise ValueError("expected one articulation")
    builder = builders[0]
    if not cfg.get("attach_visual", False):
        for link in builder.link_builders:
            link.visual_records.clear()
    return builder


def clip_norm(vector, maximum):
    import numpy as np
    norm = np.linalg.norm(vector)
    return vector*min(1., maximum/max(norm, 1e-15))


def validate_finger_speed(cfg, dt):
    speed = cfg["finger_drive"]["speed_m_s"]
    offset = cfg["contact_offset_m"]
    if not all(math.isfinite(v) and v > 0 for v in (speed, dt, offset)):
        raise ValueError("finger speed_m_s, timestep and contact_offset_m must be finite and positive")
    # Project owner ruling 1, 2026-10-14: allow for SAPIEN float32 timestep representation error.
    if speed * dt > offset * (1 + 1e-6):
        raise ValueError("finger speed_m_s * timestep must not exceed contact_offset_m * (1 + 1e-6)")


def advance_finger_target(current, target, speed, dt):
    distance = speed * dt
    return current + max(-distance, min(distance, target - current))


def validate_finger_velocity_drive(cfg):
    drive = cfg["finger_drive"]
    damping, force = drive["motion_damping_ns_m"], drive["force_limit_n"]
    if drive["motion_stiffness_n_m"] != 0:
        raise ValueError("finger motion_stiffness_n_m must be zero for velocity drive")
    if not all(math.isfinite(v) and v > 0 for v in (damping, force)):
        raise ValueError("finger motion damping and force limit must be finite and positive")
    if damping * drive["speed_m_s"] < force * (1 - 1e-6):
        raise ValueError("finger motion damping * speed must reach the force limit when blocked")


def finger_velocity_settings(actual, target, cfg, dt):
    """Independent actual-q control; no accumulated spring target during motion."""
    if abs(target - actual) <= cfg["speed_m_s"] * dt:
        return {"mode": "position_hold", "position_target_m": target,
                "velocity_target_m_s": 0., "stiffness_n_m": cfg["stiffness_n_m"],
                "damping_ns_m": cfg["damping_ns_m"], "force_limit_n": cfg["force_limit_n"]}
    return {"mode": "velocity", "position_target_m": actual,
            "velocity_target_m_s": math.copysign(cfg["speed_m_s"], target - actual),
            "stiffness_n_m": cfg["motion_stiffness_n_m"],
            "damping_ns_m": cfg["motion_damping_ns_m"], "force_limit_n": cfg["force_limit_n"]}


class GripperRig:
    def __init__(self, scene, cfg, output):
        import sapien
        self.scene, self.cfg = scene, cfg
        groups = []
        for entity in scene.entities:
            for component in entity.components:
                if isinstance(component, sapien.physx.PhysxRigidBaseComponent):
                    groups.extend((entity.name, list(s.get_collision_groups())) for s in component.get_collision_shapes())
        assert_group_available(groups)
        self.external_groups = groups
        from .site import require
        path = derive_urdf(cfg.get("robotwin_root") or require("TELEOP_ROBOTWIN_ROOT"), output)
        builder = parse_builder(scene, path, False, cfg)
        self.main = builder.build()
        self.secondary = builder.build()
        # b1's link->entity ownership is weak; keep entities alive off-scene.
        self.entities = {"main": [l.entity for l in self.main.get_links()],
                         "secondary": [l.entity for l in self.secondary.get_links()]}
        self.inactive_data = {}
        for role, art in (("main", self.main), ("secondary", self.secondary)):
            if "solver_iterations" in cfg:
                art.set_solver_position_iterations(cfg["solver_iterations"]["position"])
                art.set_solver_velocity_iterations(cfg["solver_iterations"]["velocity"])
            for link in art.get_links():
                link.entity.name = role + "/" + link.name
                self.configure_shapes(link)
            self.set_groups(art, NORMAL_GROUP)
            for joint in art.get_active_joints():
                drive = cfg["finger_drive"]
                joint.set_drive_property(drive["stiffness_n_m"], drive["damping_ns_m"],
                                         drive["force_limit_n"], mode="force")
                joint.set_drive_velocity_target(0)
        self.target = list(cfg["initial_pose"])
        self.finger_target = cfg["initial_opening_m"]
        self.finger_drive_targets = dict.fromkeys(("main", "secondary"), self.finger_target)
        self.finger_drives = {"main": {}, "secondary": {}}
        self.initialize(self.main, self.target, [self.finger_target]*2)
        self.initialize(self.secondary, self.target, [self.finger_target]*2)
        for role in ("secondary",):
            art = getattr(self, role)
            self.set_groups(art, GHOST_GROUP)
            self.inactive_data[role] = articulation_data(art, False)
            scene.remove_articulation(art)
        self.frozen = None
        self.original_limits = {j.name: j.get_limits().tolist() for j in self.main.get_active_joints()}
        self.inactive_data["frozen"] = articulation_data(self.main, False)
        self.external_bodies = [c for e in scene.entities for c in e.components
                                if isinstance(c, sapien.physx.PhysxRigidBaseComponent)
                                and c not in self.main.get_links()]

    def configure_shapes(self, body):
        for shape in body.get_collision_shapes():
            shape.set_contact_offset(self.cfg["contact_offset_m"])
            shape.set_rest_offset(self.cfg["rest_offset_m"])

    @staticmethod
    def set_groups(art, groups):
        for link in art.get_links():
            for shape in link.get_collision_shapes():
                shape.set_collision_groups(groups)

    @staticmethod
    def initialize(art, pose, qpos):
        import sapien
        art.set_root_pose(sapien.Pose(pose[:3], pose[3:]))
        art.set_qpos(qpos)
        art.set_qvel([0, 0])
        art.set_root_linear_velocity([0, 0, 0])
        art.set_root_angular_velocity([0, 0, 0])

    def freeze(self, sim_time):
        # CPU PhysX b1: already-LIMITED finger limits and root type may change
        # in-scene outside simulate/fetchResults; main q/targets are preserved.
        pose = pose_data(self.main.get_root_pose())
        qpos = list(map(float, self.main.get_qpos()))
        targets = {j.name: float(j.get_drive_target()[0]) for j in self.main.get_active_joints()}
        self.main.root.joint.type = "fixed"
        self.main.root.wake_up()
        caps = {}
        for joint, q in zip(self.main.get_active_joints(), qpos):
            original = self.original_limits[joint.name][0]
            high = ratchet_upper(q, original[1], self.cfg["freeze"]["limit_margin_m"])
            joint.set_limits([[original[0], high]])
            caps[joint.name] = high
        self.frozen = {"pose": pose, "qpos": qpos, "finger_targets": targets,
                       "upper_limits_m": caps, "sim_time_s": sim_time}
        if getattr(self, "schema_version", 4) >= 5:
            self.frozen["finger_command_target_m"] = self.finger_target
            if self.schema_version >= 6:
                self.reset_finger_drives(self.main, "main")
            else:
                self.finger_drive_targets["main"] = sum(qpos)/2
        self.set_groups(self.secondary, GHOST_GROUP)
        for entity in self.entities["secondary"]:
            self.scene.add_entity(entity)
        self.initialize(self.secondary, pose, qpos)
        self.target = pose
        self.finger_target = sum(qpos)/2
        if getattr(self, "schema_version", 4) >= 5:
            if self.schema_version >= 6:
                self.reset_finger_drives(self.secondary, "secondary")
            else:
                self.finger_drive_targets["secondary"] = self.finger_target

    def restore(self, sim_time):
        self.inactive_data["secondary"] = articulation_data(self.secondary, False)
        self.scene.remove_articulation(self.secondary)
        self.set_groups(self.secondary, GHOST_GROUP)
        self.inactive_data["frozen"] = articulation_data(self.main, False)
        for joint in self.main.get_active_joints():
            joint.set_limits(self.original_limits[joint.name])
        self.main.root.joint.type = "free"
        self.main.set_root_linear_velocity([0, 0, 0])
        self.main.set_root_angular_velocity([0, 0, 0])
        self.main.root.wake_up()
        # Actual finger q/velocity and preload stayed on this articulation.
        self.target = list(self.frozen["pose"])
        if getattr(self, "schema_version", 4) >= 5:
            self.finger_target = self.frozen["finger_command_target_m"]
            if self.schema_version >= 6:
                self.reset_finger_drives(self.main, "main")
            else:
                self.finger_drive_targets["main"] = float(sum(self.main.get_qpos())/2)
        else:
            self.finger_target = self.frozen["finger_targets"][JOINTS[0]]

    def actual_data(self, role, active):
        if role == "frozen":
            # Schema-v3 compatibility: snapshot alias, never another object.
            return articulation_data(self.main, True) if active else self.inactive_data[role]
        if role == "main":
            return articulation_data(self.main, True)  # physically present even frozen
        return articulation_data(self.secondary, True) if active else self.inactive_data[role]

    def drive(self, art, sim_time):
        import numpy as np
        from .session import quat_multiply
        cfg = self.cfg["root_drive"]
        current = art.get_root_pose()
        position_error = np.asarray(self.target[:3])-current.p
        force_raw = cfg["stiffness_n_m"]*position_error - cfg["damping_ns_m"]*art.get_root_linear_velocity()
        force = clip_norm(force_raw, cfg["force_limit_n"])
        error = np.asarray(quat_multiply(self.target[3:], (current.q[0], *(-current.q[1:]))))
        if error[0] < 0:
            error = -error
        length = np.linalg.norm(error[1:])
        rotation = error[1:]*(2*np.arctan2(length, error[0])/max(length, 1e-15))
        torque_raw = cfg["stiffness_nm_rad"]*rotation - cfg["damping_nms_rad"]*art.get_root_angular_velocity()
        torque = clip_norm(torque_raw, cfg["torque_limit_nm"])
        art.get_root().add_force_torque(force, torque)
        if getattr(self, "schema_version", 4) >= 5:
            role = "main" if art is self.main else "secondary"
            self.drive_fingers(art, role, self.finger_target)
            if role == "secondary":
                self.drive_fingers(self.main, "main", self.frozen["finger_command_target_m"])
        else:
            for joint in art.get_active_joints():
                joint.set_drive_target(self.finger_target)
        return {"force_n": list(map(float, force)), "torque_nm": list(map(float, torque)),
                "position_error_m": list(map(float, position_error)),
                "rotation_error_rad": list(map(float, rotation)),
                "force_saturated": bool(np.linalg.norm(force_raw) >= cfg["force_limit_n"]),
                "torque_saturated": bool(np.linalg.norm(torque_raw) >= cfg["torque_limit_nm"])}

    def reset_finger_drives(self, art, role):
        self.finger_drives[role] = {
            joint.name: {"mode": "rebase", "position_target_m": float(q), "velocity_target_m_s": 0.}
            for joint, q in zip(art.get_active_joints(), art.get_qpos())}

    def drive_fingers(self, art, role, command_target):
        if self.schema_version >= 6:
            applied = {}
            for joint, actual, velocity in zip(art.get_active_joints(), art.get_qpos(), art.get_qvel()):
                settings = finger_velocity_settings(float(actual), command_target,
                                                    self.cfg["finger_drive"], self.scene.get_timestep())
                settings["actual_q_before_m"] = float(actual)
                settings["actual_qvel_before_m_s"] = float(velocity)
                joint.set_drive_property(settings["stiffness_n_m"], settings["damping_ns_m"],
                                         settings["force_limit_n"], mode="force")
                joint.set_drive_target(settings["position_target_m"])
                joint.set_drive_velocity_target(settings["velocity_target_m_s"])
                applied[joint.name] = settings
            self.finger_drives[role] = applied
            return
        target = advance_finger_target(self.finger_drive_targets[role], command_target,
                                      self.cfg["finger_drive"]["speed_m_s"], self.scene.get_timestep())
        self.finger_drive_targets[role] = target
        for joint in art.get_active_joints():
            joint.set_drive_target(target)

    def overlap_blockers(self):
        """Conservative actual cooked-geometry AABBs, expanded by contact offsets.

        An intersecting AABB means *possibly* overlapping, never a penetration
        claim. Finite boxes form this phase's table; planes use signed distance.
        """
        import numpy as np
        import sapien
        result = set()
        for link in self.secondary.get_links():
            bounds = link.compute_global_aabb_tight()
            margin = max((s.get_contact_offset() for s in link.get_collision_shapes()), default=0)
            low, high = bounds[0]-margin, bounds[1]+margin
            for body in self.external_bodies:
                shapes = body.get_collision_shapes()
                other_margin = max((s.get_contact_offset() for s in shapes), default=0)
                planes = [s for s in shapes if isinstance(s, sapien.physx.PhysxCollisionShapePlane)]
                if planes:
                    corners = np.asarray([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1])
                                          for z in (low[2], high[2])])
                    for plane in planes:
                        transform = (body.pose*plane.local_pose).to_transformation_matrix()
                        normal = transform[:3, 0]
                        if np.min((corners-transform[:3, 3])@normal) <= other_margin:
                            result.add(body.entity.name)
                elif shapes:
                    other = body.compute_global_aabb_tight()
                    if np.all(high >= other[0]-other_margin) and np.all(other[1]+other_margin >= low):
                        result.add(body.entity.name)
        return sorted(result)

    def group_audit(self):
        result = {"external": self.external_groups}
        for role, art in (("main", self.main), ("secondary", self.secondary)):
            result[role] = {l.name: [list(s.get_collision_groups()) for s in l.get_collision_shapes()]
                            for l in art.get_links()}
        result["solver_iterations"] = {role: [art.get_solver_position_iterations(), art.get_solver_velocity_iterations()]
                                       for role, art in (("main", self.main), ("secondary", self.secondary))}
        return result


def set_finger_targets(art, targets):
    """Copy by joint name, preserving the actual drive targets rather than q."""
    for joint in art.get_active_joints():
        joint.set_drive_target(targets[joint.name])
        joint.set_drive_velocity_target(0)


def ratchet_upper(actual, original_upper, margin):
    """Freeze-time cap; positive width required by PhysX LIMITED joints.

    10 um test margin avoids zero-width when fully closed. The cap is held
    for the entire freeze; drive targets and force limits remain unchanged.
    """
    return min(original_upper, max(margin, actual + margin))
