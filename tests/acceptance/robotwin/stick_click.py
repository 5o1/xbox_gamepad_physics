"""Preregistered stick-click force/contact detection; no signal shaping."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from tests.acceptance import load_suite
from tests.acceptance.records import ResultSink
from tests.acceptance.robotwin.executor import RobotwinPressExecutor

PROTOCOL_PATH = Path(__file__).with_name("stick_click_protocol.json")
P = json.loads(PROTOCOL_PATH.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def setup(side, angle=0, hold=True, *, timestep=None):
    suite = load_suite()
    case = suite.case("L3" if side == "left" else "R3")
    e = RobotwinPressExecutor()
    e.setup([*case.root_pose.position_m, *case.root_pose.orientation_wxyz],
            P["dt_s"] if timestep is None else timestep)
    e.side = side
    e.cap = e.links[side+"_stick"]
    # Store the actual cooked neutral cap center in link coordinates.
    from tests.acceptance.robotwin.probe import cooked_vertices
    vertices = np.concatenate(cooked_vertices(e.cap))
    center = (vertices.min(0)+vertices.max(0))/2
    matrix = e.cap.pose.to_transformation_matrix()
    e.center_local = matrix[:3, :3].T @ (center-matrix[:3, 3])
    e.inward = -e.links["controller_body"].pose.to_transformation_matrix()[:3, 2]
    if hold:
        for suffix, target in (("x", math.radians(angle)), ("y", 0.)):
            j = e.joints[side+"_stick_"+suffix]
            j.set_drive_properties(P["T1"]["tilt_fixture_stiffness_nm_per_rad"],
                P["T1"]["tilt_fixture_damping_nms_per_rad"],
                force_limit=P["T1"]["tilt_fixture_effort_nm"], mode="force")
            j.set_drive_target(target)
    for _ in range(round(P["settle_s"]/e.dt)):
        e.scene.step()
    return e


def shaft(e):
    matrix = e.cap.pose.to_transformation_matrix()
    inward = -matrix[:3, 2]
    center = matrix[:3, :3] @ e.center_local + matrix[:3, 3]
    return inward, center


def sample(e):
    q = e.gamepad.joint_positions()[e.side+"_stick_click"]
    inward, _ = shaft(e)
    cosine = float(np.clip(inward @ e.inward, -1., 1.))
    return {"q_m": q, "raw_fraction": q/P["travel_m"],
            "signal": e.gamepad.gamepad_state().channel(e.side+"_stick"),
            "shaft_angle_deg": math.degrees(math.acos(cosine)), "cosine": cosine}


def axial_step(e, force):
    inward, center = shaft(e)
    e.cap.add_force_at_point(force*inward, center)
    e.scene.step()
    return {**sample(e), "applied_force_n": force, "force_vector_n": (force*inward).tolist(),
            "application_point_m": center.tolist()}


def t1(output, *, stop_on_failure=True, cases=None, timestep=None):
    results = []
    for side in ("left", "right"):
        for angle in P["T1"]["angles_deg"]:
            if cases is not None and (side, angle) not in cases:
                continue
            e = setup(side, angle, timestep=timestep)
            rows = []
            sink = ResultSink(output/f"{side}_{angle}"/"trace.jsonl")
            try:
                steps = round(3/e.dt)
                for i in range(2*steps+1):
                    force = 12*(i/steps if i <= steps else (2*steps-i)/steps)
                    row = {**axial_step(e, force), "time_s": (i+1)*e.dt, "loading": i <= steps}
                    rows.append(row)
                    sink.write(row)
            finally:
                sink.close()
            loading = [r for r in rows if r["loading"]]
            crossing = lambda level: next((r["applied_force_n"] for r in loading if r["signal"] >= level), None)
            f05, f50, f95 = [crossing(v) for v in (.05, .5, .95)]
            window = f95-f05 if f95 is not None and f05 is not None else None
            expected = 7.4/math.cos(math.radians(angle))
            low = [r for r in rows if r["applied_force_n"] < .9*7.4/r["cosine"]]
            low_max = max(max(r["signal"], r["raw_fraction"]) for r in low)
            angle_error = max(abs(r["shaft_angle_deg"]-angle) for r in rows)
            passed = (low_max <= .05 and window is not None and window <= 1
                      and f50 is not None and abs(f50/expected-1) <= .1
                      and max(rows[-1]["signal"], rows[-1]["raw_fraction"]) <= .05 and angle_error <= .5)
            results.append({"side": side, "angle_deg": angle, "trigger_force_n": f50,
                "predicted_force_n": expected, "transition_window_n": window,
                "low_force_max_signal_or_fraction": low_max, "final": rows[-1],
                "max_angle_error_deg": angle_error, "passed": passed})
            save(output/"results.json", {"passed": all(r["passed"] for r in results), "results": results})
            if not passed and stop_on_failure:
                return False
    return True


def t2(output, *, timestep=None):
    results = []
    for side in ("left", "right"):
        for multiplier in P["T2"]["force_multipliers"]:
            e = setup(side, timestep=timestep)
            rows = []
            sink = ResultSink(output/f"{side}_{multiplier}"/"trace.jsonl")
            try:
                for i in range(round(1/e.dt)):
                    row = {**axial_step(e, multiplier*7.4), "time_s": (i+1)*e.dt}
                    rows.append(row)
                    sink.write(row)
            finally:
                sink.close()
            stable = rows[-round(.5/e.dt):]
            low = max(max(r["signal"], r["raw_fraction"]) for r in stable)
            high = min(min(r["signal"], r["raw_fraction"]) for r in stable)
            middle = lambda samples: sum(.05 < r["signal"] < .95 for r in samples)/len(samples)
            passed = low <= .05 if multiplier <= .95 else high >= .95
            results.append({"side": side, "multiplier": multiplier, "force_n": multiplier*7.4,
                "stable_max": low, "stable_min": high, "middle_time_fraction": middle(rows),
                "stable_middle_time_fraction": middle(stable), "passed": passed})
            save(output/"results.json", {"passed": all(r["passed"] for r in results), "results": results})
            if not passed:
                return False
    return True


def t3(output):
    suite = load_suite()
    results = []
    for side in ("left", "right"):
        for normal_force in P["T3"]["normal_forces_n"]:
            e = setup(side, hold=False)
            plan = suite.case(side+"_x_pos").plan
            tangent = np.asarray(plan["direction"])
            tangent -= e.inward*(tangent @ e.inward)
            tangent /= np.linalg.norm(tangent)
            outward = -np.asarray(plan["direction"])
            start = np.asarray(plan["point_m"])+outward*(suite.settings["radius_m"]+.0002)
            e.add_ball(start, suite)
            rows = []
            sink = ResultSink(output/f"{side}_{normal_force}"/"trace.jsonl")
            try:
                for i in range(round(2.6/e.dt)):
                    age = i*e.dt
                    target = start+tangent*min(.008, age*.005)
                    error = float((target-e.ball.pose.p) @ tangent)
                    velocity = float(e.ball.linear_velocity @ tangent)
                    tangential = np.clip(3000*error-12*velocity, -16., 16.)
                    force = tangential*tangent+normal_force*e.inward+np.array([0, 0, .05*9.81])
                    e.apply_ball_force(force)
                    e.scene.step()
                    contacts, internal = e.contacts()
                    normal_vertical, total_vertical, cap_contacts = 0., 0., 0
                    for contact in contacts:
                        if side+"_stick" not in contact["bodies"]:
                            continue
                        cap_contacts += len(contact["points"])
                        for point in contact["points"]:
                            impulse = np.asarray(point["impulse_ns"])/e.dt
                            normal = np.asarray(point["normal"])
                            # Absolute inward component avoids API body-order ambiguity.
                            normal_vertical += abs(float((impulse @ normal)*(normal @ e.inward)))
                            total_vertical += abs(float(impulse @ e.inward))
                    row = {**sample(e), "time_s": (i+1)*e.dt, "normal_force_command_n": normal_force,
                        "probe_force_n": force.tolist(), "normal_vertical_contact_n": normal_vertical,
                        "total_vertical_contact_n": total_vertical, "cap_contact_points": cap_contacts,
                        "contacts": contacts, "internal_pairs": internal, "probe_position_m": e.ball.pose.p.tolist()}
                    rows.append(row)
                    sink.write(row)
            finally:
                sink.close()
            scored = [r for r in rows if r["time_s"] > .2 and r["cap_contact_points"]
                      and r["normal_vertical_contact_n"] < 6.66]
            maximum = max((max(r["signal"], r["raw_fraction"]) for r in scored), default=None)
            tilt = max(r["shaft_angle_deg"] for r in rows)
            passed = maximum is not None and maximum <= .05 and tilt >= 1
            results.append({"side": side, "normal_force_n": normal_force,
                "scored_contact_steps": len(scored), "max_signal_or_fraction_below_limit": maximum,
                "max_tilt_deg": tilt, "passed": passed})
            save(output/"results.json", {"passed": all(r["passed"] for r in results), "results": results})
    return all(r["passed"] for r in results)


def neutral(output):
    e = setup("left", hold=False)
    signals = e.gamepad.gamepad_state().as_dict()
    # Unchanged name-addressed signal encoder/decoder, including intermediate travel.
    controller = e.gamepad._signal_controller
    roundtrip = []
    for side in ("left", "right"):
        for fraction in (0., .25, .5, .75, 1.):
            positions = dict.fromkeys(e.joints, 0.)
            positions[side+"_stick_click"] = fraction*P["travel_m"]
            state = controller.encode(positions)
            decoded = controller.decode_joint_targets(state)
            roundtrip.append({"side": side, "fraction": fraction, "signal": state.channel(side+"_stick"),
                              "decoded_q_m": decoded[side+"_stick_click"]})
    passed = max(abs(v) for v in signals.values()) <= 1e-4 and all(
        abs(r["signal"]-r["fraction"]) < 1e-10 and abs(r["decoded_q_m"]-r["fraction"]*.0004) < 1e-10
        for r in roundtrip)
    save(output/"results.json", {"passed": passed, "signals_after_1s": signals, "roundtrip": roundtrip})
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", choices=["T1", "T2", "T3", "neutral"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    save(args.output/"registration.json", {"sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(), "protocol": P})
    passed = {"T1": t1, "T2": t2, "T3": t3, "neutral": neutral}[args.test](args.output)
    print(json.dumps({"test": args.test, "passed": passed}))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
