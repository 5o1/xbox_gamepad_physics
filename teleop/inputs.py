"""Ordered input execution at physics boundaries, with post-step acknowledgement."""
from .session import Command
from .views import VIEWS
from .cursor import mouse_translation, key_rotation, depth_translation

KEY_AXES = {"KeyW": (0, 1), "KeyS": (0, -1), "KeyA": (1, 1), "KeyD": (1, -1),
            "KeyQ": (2, 1), "KeyE": (2, -1)}


class Inputs:
    def __init__(self, repeat_seconds=.05, lease_seconds=.2, *, camera_relative=False,
                 input_config=None, cursor_config=None):
        self.camera_relative = camera_relative
        self.input_config, self.cursor_config = input_config, cursor_config
        self.repeat_seconds = repeat_seconds
        self.lease_seconds = lease_seconds
        self.seq = self.applied_seq = self.prepared_seq = 0
        self.armed = False
        self.keys = set()
        self.pending = []
        self.priority_stop = None
        self.next_repeat = 0.
        self.view = "front"
        self.events = []
        self.cancelled = []
        self.hold = False
        self.hold_reason = None
        self.last_activity_ns = None

    def accept(self, message, boundary_step):
        self.last_activity_ns = message.get("received_ns", self.last_activity_ns)
        if message["kind"] == "heartbeat":
            return True
        seq = message["seq"]
        if seq <= self.seq:
            return False
        self.seq = seq
        self.events.append({"seq": seq, "kind": message["kind"], "reason": message.get("reason"),
                            "received_ns": message.get("received_ns"), "boundary_step": boundary_step,
                            **{k:message[k] for k in ("screen_pixels","grip","fine","keys","view","event_time_ms","toggle_gamepad") if k in message}})
        if message["kind"] in ("stop", "disconnect"):
            self.cancelled.extend(m["seq"] for m in self.pending)
            self.pending.clear()
            self.priority_stop = message
        else:
            self.pending.append(message)
        return True

    def held_command(self, sim_time, force, pose):
        if not self.armed or (not force and sim_time+1e-12 < self.next_repeat):
            return Command()
        self.next_repeat = sim_time+self.repeat_seconds
        fine=bool(self.keys & {"ShiftLeft","ShiftRight"})
        if self.camera_relative:
            scale=self.input_config["fine" if fine else "coarse"]
            return Command(translation=depth_translation(self.view,self.keys),
                           rotation=key_rotation(self.view,self.keys,self.cursor_config["initial_pose"],scale["rotation_degrees"],
                                                 self.cursor_config["front_reference_m"]),fine=fine)
        axes=[0,0,0]
        for key in self.keys:
            if key in KEY_AXES:
                axis,direction=KEY_AXES[key];axes[axis]+=direction
        return Command(translation=tuple(axes),fine=fine)

    def command(self, sim_time, boundary_ns=None, *, pose=None, finger_target=None):
        self.prepared_seq = self.applied_seq
        self.hold = False
        if (self.armed and boundary_ns is not None and self.last_activity_ns is not None
                and boundary_ns-self.last_activity_ns >= self.lease_seconds*1e9):
            self.cancelled.extend(m["seq"] for m in self.pending)
            self.pending.clear()
            self.priority_stop = {"seq": self.applied_seq, "kind": "stop", "reason": "lease-expired"}
            self.events.append({"kind": "lease-expired", "seq": self.seq,
                                "received_ns": self.last_activity_ns+int(self.lease_seconds*1e9)})
        if self.priority_stop:
            message, self.priority_stop = self.priority_stop, None
            self.keys.clear()
            self.armed = False
            self.hold = True
            self.hold_reason = message.get("reason", message["kind"])
            self.prepared_seq = message["seq"]
            # Empty command preserves BOTH existing root target and finger preload.
            # Phase-1 Command.stop deliberately rebases; live safety must not use it.
            return Command()
        force_key_tick = False
        while self.pending:
            message = self.pending.pop(0)
            kind = message["kind"]
            if not self.armed and kind not in ("focus","view"):
                self.cancelled.append(message["seq"])
                continue
            self.prepared_seq = message["seq"]
            if kind == "focus":
                self.keys.clear()
                self.armed = True
                self.hold_reason = None
            elif kind == "view":
                if message["view"] in VIEWS:
                    self.view = message["view"]
            elif self.armed and kind == "keys":
                self.keys = set(message["keys"])
                force_key_tick = True
            elif self.armed and kind == "delta":
                fine=message.get("fine",False)
                translation=(0,0,0)
                rotation = tuple(message.get("rotation", (0, 0, 0)))
                opening=message.get("opening",0)
                if self.camera_relative:
                    scale=self.input_config["fine" if fine else "coarse"]
                    if "screen_pixels" in message:
                        gain=self.cursor_config["mouse_mm_per_pixel"]*(self.cursor_config["fine_mouse_scale"] if fine else 1)
                        displacement=mouse_translation(self.view,message["screen_pixels"],gain)
                        translation=tuple(v/scale["translation_m"] for v in displacement)
                    if "grip" in message:
                        desired=self.input_config["closed_target_m" if message["grip"]=="close" else "open_target_m"]
                        opening=(desired-finger_target)/scale["opening_m"]
                    if not (message.get("toggle",False) or message.get("toggle_gamepad",False)):
                        held=self.held_command(sim_time,force_key_tick,pose)
                        held_scale=self.input_config["fine" if held.fine else "coarse"]
                        translation=tuple(a+b*held_scale["translation_m"]/scale["translation_m"] for a,b in zip(translation,held.translation))
                        rotation=tuple(a+b*held_scale["rotation_degrees"]/scale["rotation_degrees"] for a,b in zip(rotation,held.rotation))
                return Command(translation=translation,rotation=rotation,opening=opening,
                               toggle=message.get("toggle",False),toggle_gamepad=message.get("toggle_gamepad",False),fine=fine)
        return self.held_command(sim_time,force_key_tick,pose)

    def commit(self):
        """Called only after Session.step completed; publish with that exact snapshot."""
        self.applied_seq = self.prepared_seq
        return self.applied_seq
