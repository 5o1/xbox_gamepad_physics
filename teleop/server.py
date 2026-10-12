"""Physics-only scene owner; fixed 4 ms steps, latest-state publication."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import socket
import signal
from threading import Event
import time

from .inputs import Inputs
from .session import Command
from .stream.ipc import Latest, SNAPSHOT_CAPACITY
from .stream.commands import command_address


def live_config(path, collision="sdf"):
    from experiments.runner import load_config
    from xbox_gamepad_physics.resources import resource_path
    from .site import resolve_config
    cfg = resolve_config(load_config(path))
    cfg["scene"]["render"] = False
    cfg["gamepad"]["attach_visual"] = True
    cfg["gamepad"]["fixed_root"] = True
    cfg["stream"]["gamepad_freeze"] = True
    cfg["gamepad"]["collision"] = collision
    mesh = resource_path("common", "xbox_one_s", "collision/coacd/shell.obj")
    low = min(float(line.split()[3]) for line in mesh.read_text().splitlines() if line.startswith("v "))
    cfg["gamepad"]["pose"] = [0,0,-low+.0005,1,0,0,0]
    cfg["teleop"]["attach_visual"] = True
    cfg["teleop"]["fixture"]["include_block"] = False
    # Park clear of the buttons in the perpendicular view; drive/mass values stay unchanged.
    cfg["teleop"]["initial_pose"] = list(cfg["stream"]["cursor"]["initial_pose"])
    if abs(cfg["scene"]["timestep"]-.004) > 1e-12:
        raise ValueError("phase 2 requires the phase-1 4 ms timestep")
    return cfg


def run(args):
    stopping = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    from .runtime import make_session
    run_dir = args.run
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg = live_config(args.config, args.collision)
    if args.ball_plan:
        bundle=json.loads(args.ball_plan.read_text())
        cfg["gamepad"]["pose"]=bundle["gamepad_pose"]
        cfg["stream"]["preserve_gamepad_pose"]=True
    if args.ball_case:
        cfg["teleop"]["initial_pose"] = [1,1,1,1,0,0,0]
    (run_dir/"live_config.json").write_text(json.dumps(cfg, indent=2)+"\n")
    latest = Latest(run_dir/"snapshot.mmap", SNAPSHOT_CAPACITY)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(command_address(run_dir))
    sock.setblocking(False)
    scripted = json.loads(args.commands.read_text()) if args.commands else None
    controls = Inputs(cfg.get("stream", {}).get("input_repeat_seconds", .05),
                      cfg.get("stream", {}).get("control_lease_seconds", .2), camera_relative=True,
                      input_config=cfg["teleop"]["input"], cursor_config=cfg["stream"]["cursor"])
    with (run_dir/"record.jsonl").open("w") as record, (run_dir/"physics_timing.jsonl").open("w") as timing:
        session = make_session(cfg, run_dir, record)
        from .ball_probe import BallProbe
        probe = BallProbe(session, run_dir, args.ball_case, args.ball_radius_m, args.ball_plan) if args.ball_case else None
        origin = time.monotonic()
        while not stopping.is_set() and (args.steps is None or session.index < args.steps):
            deadline = origin+session.index*.004
            delay = deadline-time.monotonic()
            if delay > 0:
                time.sleep(delay)
            boundary_ns = time.monotonic_ns()
            controls.events = []
            while True:
                try:
                    data = sock.recv(65536)
                except BlockingIOError:
                    break
                message = json.loads(data)
                if probe and message.get("kind") == "probe":
                    probe.request(message)
                else:
                    controls.accept(message, session.index)
            if scripted is None:
                command = controls.command(session.index*.004, boundary_ns,
                                           pose=session.rig.target, finger_target=session.rig.finger_target)
            else:
                raw = scripted[session.index] if session.index < len(scripted) else {}
                command = Command(**raw)
                controls.seq = controls.prepared_seq = session.index+1
            command_ready_ns = time.monotonic_ns()
            session.input_metadata = {"last_input_seq":controls.prepared_seq, "received_seq":controls.seq,
                                      "events":controls.events, "boundary_ns":boundary_ns,
                                      "hold":controls.hold, "hold_reason":controls.hold_reason,
                                      "last_activity_ns":controls.last_activity_ns,
                                      "command_ready_ns":command_ready_ns,
                                      "cancelled_seqs":list(controls.cancelled)}
            if probe:probe.before_step()
            row = session.step(command)["state"]
            probe_state = probe.after_step(row) if probe else None
            controls.commit()
            snapshot = {k:row[k] for k in ("step","state","ghost","ghost_blocked","geometry_blockers",
                                         "main","secondary","frozen","gamepad","signals","canonical_state","fixtures","target_pose")}
            snapshot.update({k:row[k] for k in ("gamepad_frozen","gamepad_transition") if k in row})
            snapshot.update({"last_input_seq": controls.applied_seq, "view": controls.view,
                             "input_config": cfg["teleop"]["input"], "config": cfg,
                             "cursor_config": cfg["stream"]["cursor"],
                             "received_seq": controls.seq, "cancelled_seqs": controls.cancelled,
                             "hold_reason": controls.hold_reason})
            if probe_state:
                snapshot["probe"] = probe_state
                snapshot["view"] = probe_state["view"]
            latest.write(json.dumps(snapshot, separators=(",", ":")).encode())
            timing.write(json.dumps({"step": row["step"], "boundary_ns": boundary_ns,
                                     "end_ns": time.monotonic_ns(), "physics_seconds":row["physics_seconds"],
                                     "last_input_seq": controls.applied_seq, "command":asdict(command),
                                     "last_activity_ns":controls.last_activity_ns, "command_ready_ns":command_ready_ns,
                                     "input_events":controls.events, "hold":controls.hold, "hold_reason":controls.hold_reason, "lateness_s":max(0.,boundary_ns/1e9-deadline)})+"\n")
    sock.close()
    latest.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/teleop_gripper.yaml"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--commands", type=Path)
    from .ball_probe import CASES
    parser.add_argument("--ball-case", choices=CASES)
    parser.add_argument("--ball-radius-m", type=float)
    parser.add_argument("--ball-plan", type=Path)
    parser.add_argument("--collision", choices=["coacd","sdf"], default="sdf")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
