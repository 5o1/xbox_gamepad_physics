"""Pure command/state/filter rules and the synchronous physics-step session."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math
import time
from .record import write_row

NORMAL_GROUP = (1, 1, 0x40000000, 0x4752)
GHOST_GROUP = (0, 0, 0x40000000, 0x4752)
SCHEMA_VERSION = 3


def collision_allowed(a, b):
    """SAPIEN b1 ordinary-shape filter; triggers are outside this contract."""
    if a[3] >> 16 != b[3] >> 16:
        return False
    if a[2] & b[2] and (a[3] & 0xFFFF) == (b[3] & 0xFFFF):
        return False
    return bool((a[0] & b[1]) or (b[0] & a[1]))


def assert_group_available(groups):
    for name, group in groups:
        if group[2] & NORMAL_GROUP[2] or group[3] == NORMAL_GROUP[3]:
            raise ValueError(f"reserved gripper collision group occupied by {name}: {group}")


@dataclass(frozen=True)
class Command:
    """Per-step ticks in WORLD axes; rotation is an axis-angle tick vector.

    Fine ticks are 1 mm / 1 degree. Positive opening ticks open both fingers.
    Toggle is an edge event, not a held key. Stop holds the actual pose.
    """
    translation: tuple[float, float, float] = (0, 0, 0)
    rotation: tuple[float, float, float] = (0, 0, 0)
    opening: float = 0
    fine: bool = False
    toggle: bool = False
    stop: bool = False
    toggle_gamepad: bool = False

    def __post_init__(self):
        if len(self.translation) != 3 or len(self.rotation) != 3:
            raise ValueError("translation and rotation need three ticks")
        if not all(math.isfinite(x) for x in (*self.translation, *self.rotation, self.opening)):
            raise ValueError("command ticks must be finite")


class State(str, Enum):
    MAIN = "main"
    SECONDARY_GHOST = "main_frozen_secondary_ghost"
    SECONDARY_NORMAL = "main_frozen_secondary_normal"


@dataclass
class StateMachine:
    minimum_ghost_seconds: float = 0.5
    state: State = State.MAIN
    ghost_started: float | None = None
    blocked: bool = False

    def __post_init__(self):
        if not math.isfinite(self.minimum_ghost_seconds) or self.minimum_ghost_seconds < 0.5:
            raise ValueError("ghost minimum must be at least 0.5 simulation seconds")

    def advance(self, toggle, sim_time, geometry_clear):
        before = self.state
        if toggle:
            if self.state == State.MAIN:
                self.state = State.SECONDARY_GHOST
                self.ghost_started = sim_time
            else:
                self.state = State.MAIN
                self.ghost_started = None
            self.blocked = False
        elif self.state == State.SECONDARY_GHOST:
            elapsed = sim_time - self.ghost_started
            ready = elapsed + 1e-12 >= self.minimum_ghost_seconds
            self.blocked = ready and not geometry_clear
            if ready and geometry_clear:
                self.state = State.SECONDARY_NORMAL
                self.blocked = False
        return before, self.state

    @property
    def ghost(self):
        return self.state == State.SECONDARY_GHOST


def quat_multiply(a, b):
    w, x, y, z = a
    v, i, j, k = b
    return (w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j,
            w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v)


def rotation_quaternion(vector):
    angle = math.sqrt(sum(x*x for x in vector))
    if angle < 1e-15:
        return (1., 0., 0., 0.)
    factor = math.sin(angle/2)/angle
    return (math.cos(angle/2), *(x*factor for x in vector))


def command_target(pose, finger, command, cfg):
    p, q = pose[:3], pose[3:]
    scale = cfg["fine" if command.fine else "coarse"]
    p = [v + tick*scale["translation_m"] for v, tick in zip(p, command.translation)]
    delta = rotation_quaternion([v*math.radians(scale["rotation_degrees"]) for v in command.rotation])
    q = quat_multiply(delta, q)
    length = math.sqrt(sum(v*v for v in q))
    q = [v/length for v in q]
    finger = min(cfg["open_target_m"], max(cfg["closed_target_m"],
                 finger + command.opening*scale["opening_m"]))
    return p + q, finger


def pose_data(pose):
    return [float(x) for x in (*pose.p, *pose.q)]


def articulation_data(art, active):
    return {"active": active, "pose": pose_data(art.get_root_pose()),
            "joints": {j.name: float(q) for j, q in zip(art.get_active_joints(), art.get_qpos())},
            "drive_targets": {j.name: float(j.get_drive_target()[0]) for j in art.get_active_joints()},
            "links": {l.name: pose_data(l.pose) for l in art.get_links()},
            "linear_velocity": list(map(float, art.get_root_linear_velocity())),
            "angular_velocity": list(map(float, art.get_root_angular_velocity())),
            "qvel": list(map(float, art.get_qvel())),
            "root_joint_type": art.root.joint.type,
            "joint_limits": {j.name: j.get_limits().tolist() for j in art.get_active_joints()}}


def canonical_data(state):
    """Serialize the loader's complete canonical state without re-encoding it."""
    return {"layout_id": state.layout_id, "values": list(state.values),
            "available_mask": list(state.available_mask), "task_mask": list(state.task_mask),
            "device_id": state.device_id}


def contact_data(scene, body_ids):
    rows = []
    for contact in scene.get_contacts():
        rows.append({"bodies": [body_ids[b] for b in contact.bodies], "points": [
            {"position_m": list(map(float, p.position)),
             "normal_world": list(map(float, p.normal)),
             "impulse_ns": list(map(float, p.impulse)), "separation_m": float(p.separation)}
            for p in contact.points]})
    return sorted(rows, key=lambda row: tuple(row["bodies"]))


class Session:
    """Call step(Command) once per physics step. All mutations precede scene.step.

    Returns state plus frame=None (phase 1 has no renderer). record is JSONL;
    header supplies config, initial fixture and backend provenance for replay.
    """
    def __init__(self, scene, gamepad, rig, cfg, record=None, header=None):
        from experiments.collision_check import internal_contact_pairs
        self.internal_contact_pairs = internal_contact_pairs
        self.scene, self.gamepad, self.rig, self.cfg = scene, gamepad, rig, cfg
        self.machine = StateMachine(cfg["ghost_minimum_seconds"])
        self.index = 0
        self.phase = None
        self.dt = scene.get_timestep()
        self.record = record
        self.body_ids = {}
        import sapien
        for entity in scene.entities:
            for body in entity.components:
                if isinstance(body, sapien.physx.PhysxRigidBaseComponent):
                    self.body_ids[body] = entity.name
        for role, art in (("main", rig.main), ("secondary", rig.secondary)):
            for link in art.get_links():
                self.body_ids[link] = role + "/" + link.name
        if record:
            write_row(record,{"type": "header", "schema_version": SCHEMA_VERSION,
                              **(header or {})})

    def step(self, command):
        started = time.perf_counter()
        sim_time = self.index*self.dt
        switch = getattr(self, 'gamepad_switch', None)
        transition = None
        if command.toggle_gamepad:
            if switch is None:
                raise ValueError('gamepad toggle requires gamepad freeze to be enabled')
            transition = switch.toggle()
            self.gamepad = switch.active
        blockers = self.rig.overlap_blockers() if self.machine.ghost else []
        before, after = self.machine.advance(command.toggle, sim_time, not blockers)
        if before != after:
            if before == State.MAIN:
                self.rig.freeze(sim_time)
            elif after == State.MAIN:
                self.rig.restore(sim_time)
            else:
                self.rig.set_groups(self.rig.secondary, NORMAL_GROUP)
        active = self.rig.main if after == State.MAIN else self.rig.secondary
        if command.stop:
            self.rig.target = pose_data(active.get_root_pose())
            self.rig.finger_target = float(sum(active.get_qpos()) / 2)
        elif not command.toggle:
            self.rig.target, self.rig.finger_target = command_target(
                self.rig.target, self.rig.finger_target, command, self.cfg["input"])
        if hasattr(self, "input_metadata"):
            self.input_metadata["targets_set_ns"] = time.monotonic_ns()
        drive = self.rig.drive(active, sim_time)
        physics_start = time.perf_counter()
        self.scene.step()
        physics_seconds = time.perf_counter() - physics_start
        if hasattr(self, "input_metadata"):
            self.input_metadata["physics_done_ns"] = time.monotonic_ns()
        state = self.gamepad.gamepad_state()  # loader's GamepadSignalController
        from xbox_gamepad_physics.state import XBOX_ONE_S_CHANNELS
        row = {"type": "step", "step": self.index, "sim_time_end_s": (self.index+1)*self.dt,
               "command": asdict(command), "state": after.value, "ghost": self.machine.ghost,
               "ghost_blocked": self.machine.blocked, "geometry_blockers": blockers,
               "target_pose": self.rig.target, "finger_target_m": self.rig.finger_target,
               "drive": drive, "main": self.rig.actual_data("main", after == State.MAIN),
               "secondary": self.rig.actual_data("secondary", after != State.MAIN),
               "frozen": self.rig.actual_data("frozen", after != State.MAIN),
               "gamepad": articulation_data(self.gamepad.articulation, True),
               "contacts": contact_data(self.scene, self.body_ids),
               "signals": {name: state.channel(name) for name in XBOX_ONE_S_CHANNELS},
               "canonical_state": canonical_data(state),
               "gamepad_internal_pairs": self.internal_contact_pairs(self.scene, self.gamepad.articulation),
               "physics_seconds": physics_seconds}
        if switch:
            row['gamepad_frozen'] = switch.frozen
            row['gamepad_transition'] = transition
            row['gamepad_collision_groups'] = switch.group_audit()
            row['gamepad_articulation_count'] = 1
            row['gamepad_between_copy_contacts'] = 0  # no second gamepad exists
        row["gripper_freeze"] = self.rig.frozen if after != State.MAIN else None
        row["phase"] = self.phase
        audit = self.rig.group_audit()
        row["gripper_collision_groups"] = {k: audit[k] for k in ("main", "secondary")}
        row["step_seconds"] = time.perf_counter() - started
        row["fixtures"] = {name: {"pose": pose_data(body.pose)}
                           for name, body in getattr(self, "objects", {}).items()}
        if hasattr(self, "input_metadata"):
            row["input"] = self.input_metadata
        if self.record:
            write_row(self.record,row)
        self.index += 1
        return {"state": row, "frame": None}
