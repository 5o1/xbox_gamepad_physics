"""Native MuJoCo execution of the public, frozen ruling20 experiment.

Only the probe's three force actuators are driven during a case. Gamepad qpos
and targets are never changed after constructing the neutral standalone scene.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from ..acceptance import load_suite, run_case
from ..acceptance.records import ResultSink, summarize
from .builder import CONTACT_NUMERICS, XML_REFERENCE
from .numerics import numerical_policy, contact_policy


def fixture_mapping(suite, policy=None):
    """Separate experiment definitions from the native numerical contact policy."""
    policy = policy or numerical_policy()
    return {
        'backend_options': {'mujoco': {'numerical_stability': policy}},
        'gamepad_contact_response': contact_policy(),
        'probe_contact_policy': 'Native default solref and solmix; no probe override in production.',
        'acceptance_step_s': policy['acceptance_step_s'],
        'physics_timestep_s': policy['physics_timestep_s'],
        'substeps_per_acceptance_step': policy['substeps_per_acceptance_step'],
        "fixture_evidence": dict(suite.evidence),
        "mass_kg": suite.settings["mass_kg"],
        "radius_m": suite.settings["radius_m"],
        "inertia_kg_m2": 2 * suite.settings["mass_kg"] * suite.settings["radius_m"] ** 2 / 5,
        "drive": "Three world-axis force actuators on a free sphere; shared ball_force clips the total 3D norm after gravity compensation. Rotation remains free.",
        "drive_source": XML_REFERENCE + "#actuator-general-joint",
        "physical_contact_mapping": None,
        "unmapped": {"sphere_material": dict(suite.fixture["sphere_material"]),
                     "sapien_mapping": dict(suite.fixture["sapien_mapping"])},
        "missing_reason": "Static/dynamic Coulomb coefficients, restitution and PhysX offsets have no established MuJoCo-equivalent mapping.",
        "numerical_contact": CONTACT_NUMERICS,
        "numerical_source": XML_REFERENCE,
        "numerical_applicability": "Explicit MuJoCo default solver/contact settings for an engine comparison, not measured gamepad or sphere parameters.",
        "numerical_effect": "Friction sets sliding/torsional/rolling contact coefficients; solref/solimp set soft constraint response; margin/gap set contact inclusion distance.",
        "uncertainty": None,
        "uncertainty_reason": "No cross-engine contact calibration or physical uncertainty measurement was supplied.",
        "integrator": "implicitfast",
        "integrator_source": "https://github.com/google-deepmind/mujoco/blob/3.16.0/doc/computation/index.rst#numerical-integration",
        "integrator_applicability": "Standalone experimental numerical policy for stiff drives; frozen timestep remains unchanged.",
    }


class MujocoPressExecutor:
    """Implement the public PressExecutor using an isolated native model per case."""

    def __init__(self, *, resource_root=None, spec_factory=None, physics_timestep_s=None):
        self.resource_root = resource_root
        self._spec_factory = spec_factory
        self._requested_physics_timestep = physics_timestep_s

    def reset_case(self, suite, case):
        import mujoco
        import numpy as np
        from .loader import make_spec

        self._mj, self._np = mujoco, np
        self.suite, self.case = suite, case
        factory = self._spec_factory or make_spec
        self.asset = factory(resource_root=self.resource_root, fixed_root=True,
                             pose=case.root_pose, attach_visual=False, collision="coacd")
        configured = getattr(self.asset, 'numerical_policy', None)
        self.policy = numerical_policy({'numerical_stability': configured} if configured else None,
                                       physics_timestep_s=self._requested_physics_timestep)
        if suite.fixture['dt_s'] != self.policy['acceptance_step_s']:
            raise ValueError('Numerical policy must preserve the frozen acceptance timestep')
        self._step_seconds = []
        spec = self.asset.spec
        spec.option.timestep = self.policy['physics_timestep_s']
        spec.option.gravity = suite.fixture["gravity_m_s2"]
        spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
        start = np.asarray(case.plan["start_m"]) - np.asarray(case.plan["direction"]) * 0.015
        body = spec.worldbody.add_body(name="ruling20_probe", pos=start)
        mass, radius = suite.settings["mass_kg"], suite.settings["radius_m"]
        body.mass = mass
        body.ipos = [0, 0, 0]
        body.iquat = [1, 0, 0, 0]
        body.inertia = [2 * mass * radius ** 2 / 5] * 3
        body.explicitinertial = True
        body.add_freejoint(name="ruling20_probe_free")
        for i, axis in enumerate(np.eye(3)):
            name = f"ruling20_probe_{i}"
            spec.add_actuator(name=name, target="ruling20_probe_free", trntype=mujoco.mjtTrn.mjTRN_JOINT,
                              gear=[*axis, 0, 0, 0], gainprm=[1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                              ctrllimited=False, forcelimited=False)
        # Deliberately omit solref/solmix: this represents an unchanged caller finger.
        probe_numerics = {k: v for k, v in CONTACT_NUMERICS.items() if k not in {'solref', 'solmix'}}
        body.add_geom(name="ruling20_probe", type=mujoco.mjtGeom.mjGEOM_SPHERE,
                      size=[radius, 0, 0], contype=1, conaffinity=1,
                      rgba=[0.8, 0.1, 0.1, 1], **probe_numerics)
        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        # Bind initializes every control from the public physical initial state.
        # No gamepad coordinates or targets are written during the press loop.
        self.gamepad = self.asset.bind(self.model, self.data)
        self._ball_id = self.model.body("ruling20_probe").id
        self._ball_geom_id = self.model.geom("ruling20_probe").id
        self._actuator_ids = [self.model.actuator(f"ruling20_probe_{i}").id for i in range(3)]
        self._gamepad_body_ids = set(range(1, self.model.nbody)) - {self._ball_id}
        mujoco.mj_forward(self.model, self.data)
        self.mapping = fixture_mapping(suite, self.policy)
        self.mapping['gamepad_contact_response'] = getattr(self.asset, 'contact_policy', None)
        probe = self.model.geom('ruling20_probe')
        self.mapping['probe_native_contact'] = {'solref': probe.solref.tolist(),
            'solmix': float(probe.solmix[0]), 'priority': int(probe.priority[0]),
            'friction': probe.friction.tolist()}

    def ball_state(self):
        velocity = self._np.zeros(6)
        self._mj.mj_objectVelocity(self.model, self.data, self._mj.mjtObj.mjOBJ_BODY,
                                  self._ball_id, velocity, 0)
        return {"position_m": self.data.xpos[self._ball_id].tolist(),
                "velocity_m_s": velocity[3:].tolist()}

    def apply_ball_force(self, force_n):
        force = self._np.asarray(force_n, dtype=float)
        if force.shape != (3,) or not self._np.isfinite(force).all():
            raise ValueError("probe force requires three finite values in newtons")
        if self._np.linalg.norm(force) > self.suite.settings["force_limit_n"] + 1e-12:
            raise ValueError("probe force exceeds the shared total norm limit")
        self.data.ctrl[self._actuator_ids] = force

    def step(self, dt_s):
        if abs(dt_s - self.policy['acceptance_step_s']) > 1e-12:
            raise ValueError("executor timestep must equal the frozen fixture timestep")
        started = time.perf_counter()
        # The common runner computes probe PD once per frozen outer step.
        # Its actuator command is held over all native physics substeps.
        for _ in range(self.policy['substeps_per_acceptance_step']):
            self._mj.mj_step(self.model, self.data)
            if not all(self._np.isfinite(v).all() for v in (self.data.qpos, self.data.qvel, self.data.qacc)):
                raise RuntimeError("MuJoCo produced a non-finite state")
            warnings = [int(w.number) for w in self.data.warning]
            if any(warnings):
                raise RuntimeError(f"MuJoCo warning counters are nonzero: {warnings}")
        # Refresh Cartesian poses and contacts for the post-step observation.
        self._mj.mj_forward(self.model, self.data)
        self._step_seconds.append(time.perf_counter() - started)

    def step_performance(self):
        values = self._np.asarray(self._step_seconds)
        return {'acceptance_step_s': self.policy['acceptance_step_s'],
                'physics_timestep_s': self.policy['physics_timestep_s'],
                'substeps_per_acceptance_step': self.policy['substeps_per_acceptance_step'],
                'measured_steps': len(values), 'mean_seconds': float(values.mean()),
                'median_seconds': float(self._np.median(values)),
                'p95_seconds': float(self._np.percentile(values, 95)),
                'measurement': 'Wall time of step(): all native substeps, warning checks and final forward; excludes common PD, sampling, JSON IO and rendering.'}

    def sample(self):
        contacts, internal = [], set()
        for index, contact in enumerate(self.data.contact):
            ids = (int(contact.geom1), int(contact.geom2))
            body_ids = tuple(int(self.model.geom_bodyid[g]) for g in ids)
            if all(b in self._gamepad_body_ids for b in body_ids):
                internal.add(tuple(sorted(body_ids)))
            if self._ball_geom_id in ids:
                wrench = self._np.zeros(6)
                self._mj.mj_contactForce(self.model, self.data, index, wrench)
                contacts.append({
                    "env_id": 0, "time_s": float(self.data.time),
                    "bodies": [self.model.body(b).name for b in body_ids],
                    "geoms": [self.model.geom(g).name for g in ids],
                    "point_m": contact.pos.tolist(), "separation_m": float(contact.dist),
                    "frame": "contact", "wrench_contact_n_nm": wrench.tolist(),
                    "contact_frame_world": contact.frame.tolist(),
                    'effective_solref': contact.solref.tolist(),
                    'effective_solimp': contact.solimp.tolist(),
                    'effective_friction': contact.friction.tolist(),
                    "force_n": None, "impulse_ns": None,
                    "missing_reason": "Wrench is reported in MuJoCo's contact frame; no aggregation or signed world-body conversion is claimed.",
                })
        state = self.gamepad.gamepad_state()
        joints = self.gamepad.joint_positions()
        excess = {}
        for name, limits in self.case.joint_limits.items():
            lower, upper = limits
            distance = max(lower - joints[name], joints[name] - upper, 0.0)
            if distance:
                excess[name] = distance
        return {
            'acceptance_step_wall_seconds': self._step_seconds[-1] if self._step_seconds else None,
            'physics_substeps_per_acceptance_step': self.policy['substeps_per_acceptance_step'],
            "probe": {"pose": [*self.data.xpos[self._ball_id].tolist(),
                                *self.data.xquat[self._ball_id].tolist()],
                      "velocity_m_s": self.ball_state()["velocity_m_s"],
                      "events": self.gamepad.physical_events()},
            "signals": state.as_dict(), "joints": joints,
            "joint_velocities": {n: self.gamepad.joint_velocity(n) for n in joints},
            "root_pose": asdict(self.gamepad.root_pose()),
            "root_twist": self.gamepad.root_twist(),
            "canonical_state": {"values": list(state.values),
                                "available_mask": list(state.available_mask),
                                "task_mask": list(state.task_mask),
                                "action_mask": list(state.action_mask)},
            "contacts": contacts, "gamepad_internal_pairs": len(internal),
            "joint_limit_excess": excess,
        }


def execute_suite(output, *, resource_root=None, suite=None, case_ids=None, physics_timestep_s=None):
    """Archive incrementally; retain null results and stop on execution errors."""
    suite = suite or load_suite()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    selected = set(case_ids) if case_ids is not None else {c.case_id for c in suite.cases}
    unknown = selected - {c.case_id for c in suite.cases}
    if unknown:
        raise ValueError(f"unknown frozen cases: {sorted(unknown)}")
    rows = [{"case": c.case_id, "status": "not_run", "physics_passed": None,
             "target_min": None, "contact_observed": None, "baseline_passed": c.baseline["passed"],
             "regressed": None, "missing_reason": "Case has not been executed."} for c in suite.cases]
    report = {"suite_id": suite.suite_id, "results": rows,
              "fixture_mapping": fixture_mapping(suite, numerical_policy(physics_timestep_s=physics_timestep_s))}

    def persist():
        report["summary"] = summarize(rows, planned=len(suite.cases))
        report["regressions"] = [r["case"] for r in rows if r["regressed"]]
        path = output / "results.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    persist()
    executor = MujocoPressExecutor(resource_root=resource_root, physics_timestep_s=physics_timestep_s)
    for index, case in enumerate(suite.cases):
        if case.case_id not in selected:
            continue
        sink = ResultSink(output / case.case_id / "trace.jsonl")
        try:
            result = run_case(executor, suite, case, sink)
            report['fixture_mapping'] = executor.mapping
            rows[index] = {**result, "status": "passed" if result["physics_passed"] else "failed",
                           'acceptance_step_timing': executor.step_performance(),
                           "baseline_passed": case.baseline["passed"],
                           "baseline": dict(case.baseline),
                           "regressed": bool(case.baseline["passed"] and not result["physics_passed"])}
        except Exception as exc:
            rows[index].update(status="execution_error", missing_reason=f"{type(exc).__name__}: {exc}")
            persist()
            raise
        finally:
            sink.close()
        persist()
    return report
