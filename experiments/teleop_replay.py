"""Replay commands in a fresh headless scene, without imposing recorded poses."""

import json
from pathlib import Path

from teleop.session import Command, SCHEMA_VERSION


def read_record(path):
    with Path(path).open() as stream:
        header = json.loads(next(stream))
        if header.get("type") != "header" or header.get("schema_version") not in (1, 2, SCHEMA_VERSION):
            raise ValueError("unsupported teleop record schema")
        rows = [json.loads(line) for line in stream]
    for index, row in enumerate(rows):
        if row.get("type") != "step" or row.get("step") != index:
            raise ValueError(f"non-contiguous record at step {index}")
    return header, rows


def numeric_difference(a, b):
    if isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys():
        return max((numeric_difference(a[k], b[k]) for k in a), default=0.)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b):
        return max((numeric_difference(x, y) for x, y in zip(a, b)), default=0.)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a-b)
    return 0. if a == b else float("inf")


def step_difference(expected, actual):
    fields = ("main", "secondary", "frozen", "gamepad", "fixtures")
    poses = max(numeric_difference(expected[k]["pose"], actual[k]["pose"])
                for k in ("main", "secondary", "frozen", "gamepad"))
    joints = max(numeric_difference(expected[k]["joints"], actual[k]["joints"])
                 for k in ("main", "secondary", "frozen", "gamepad"))
    for k in ("main", "secondary", "frozen", "gamepad"):
        poses = max(poses, numeric_difference(expected[k]["links"], actual[k]["links"]))
    poses = max(poses, numeric_difference(expected["fixtures"], actual["fixtures"]))
    signals_equal = expected["signals"] == actual["signals"]
    state_equal = all(expected[k] == actual[k] for k in ("state", "ghost", "ghost_blocked", "geometry_blockers"))
    all_physics = max(numeric_difference(expected[k], actual[k]) for k in fields)
    contacts_equal = expected["contacts"] == actual["contacts"]
    return {"step": expected["step"], "pose_max_abs": poses, "joint_max_abs": joints,
            "all_physics_max_abs": all_physics, "signals_equal": signals_equal,
            "state_equal": state_equal, "contacts_equal": contacts_equal,
            "passed": poses <= 1e-9 and joints <= 1e-9 and signals_equal and state_equal}


def replay(path, output, context=None):
    from teleop.runtime import make_session
    header, expected = read_record(path)
    if header.get("freeze_mechanism") != "fixed_root_driven_articulation":
        raise ValueError("historical fixed-proxy records can be inspected; current replay requires the v3 driven freeze mechanism")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output/"replay.jsonl").open("w") as record, (output/"differences.jsonl").open("w") as diffs:
        session = make_session(header["config"], output, record, context)
        rows, first = [], None
        for original in expected:
            session.phase = original.get("phase")
            actual = session.step(Command(**original["command"]))["state"]
            difference = step_difference(original, actual)
            diffs.write(json.dumps(difference)+"\n")
            rows.append(difference)
            if first is None and not difference["passed"]:
                first = difference
    metrics = {"passed": first is None, "steps": len(rows), "first_divergence": first,
               "max_pose_abs": max((r["pose_max_abs"] for r in rows), default=0.),
               "max_joint_abs": max((r["joint_max_abs"] for r in rows), default=0.),
               "signals_equal": all(r["signals_equal"] for r in rows),
               "contacts_equal": all(r["contacts_equal"] for r in rows)}
    (output/"metrics.json").write_text(json.dumps(metrics, indent=2)+"\n")
    return metrics


def run(cfg, ctx):
    if not cfg["params"]["record"]:
        raise ValueError("set params.record to an existing phase-1 JSONL recording")
    header, _ = read_record(cfg["params"]["record"])
    for key in ("scene", "gamepad", "profile", "teleop"):
        if cfg[key] != header["config"][key]:
            raise ValueError(f"replay configuration differs from recording: {key}")
    return replay(cfg["params"]["record"], ctx.output_dir, ctx)
