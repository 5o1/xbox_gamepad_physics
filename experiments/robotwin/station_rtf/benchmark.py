"""Instrument AQ's existing station benchmark without changing its physics.

The AQ probe is an external read-only input, copied into build/ for this run.
All scene construction, station gains, input scheduling and contact preparation
come from that probe. Individual step arrays are saved outside Git.
"""
import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import time
from unittest.mock import patch

import numpy as np


def load_probe(path):
    spec = importlib.util.spec_from_file_location("aq_engine_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aq-probe", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--condition", choices=["static", "active", "contact"], required=True)
    p.add_argument("--iterations", nargs=2, type=int)
    p.add_argument("--variant", default="default")
    p.add_argument("--sleep-threshold", type=float)
    p.add_argument("--batch-size", type=int)
    p.add_argument("--batch-library", type=Path)
    p.add_argument("--steps", type=int, default=3000)
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--always-awake", action="store_true",
                   help="Wake the gamepad before every backend step; include wake/readback in full-step timing")
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    aq = load_probe(a.aq_probe)
    import sapien
    from dexhand_workstation import collection
    # PhysX CPU workers=0 executes on the caller thread. BLAS/OMP are fixed
    # separately by the launcher; affinity is captured below.
    sapien.physx.set_scene_config(cpu_workers=0, enable_tgs=True)
    native_arrays, total_arrays = [], []
    pad_states = []
    original_factory = collection.create_backend

    class PerStepScene(aq.TimedScene):
        def __init__(self, scene):
            super().__init__(scene)
            self.samples = []
            native_arrays.append(self.samples)

        def step(self):
            start = time.perf_counter_ns()
            self.scene.step()
            elapsed = time.perf_counter_ns() - start
            self.ns += elapsed
            self.samples.append(elapsed)

    def factory(*args, **kwargs):
        backend = original_factory(*args, **kwargs)
        samples = []
        total_arrays.append(samples)
        original_step = backend.step
        root = backend.gamepad.articulation.root
        awake_record = dict(calls=0, sleeping_after_wake=0, sleeping_after_step=0)

        def step(*args, **kwargs):
            start = time.perf_counter_ns()
            if a.always_awake:
                root.wake_up()
                awake_record["sleeping_after_wake"] += int(root.sleeping)
            result = original_step(*args, **kwargs)
            if a.always_awake:
                awake_record["calls"] += 1
                awake_record["sleeping_after_step"] += int(root.sleeping)
            samples.append(time.perf_counter_ns() - start)
            return result

        backend.step = step
        original_close = backend.close

        def close():
            art = backend.gamepad.articulation
            owners = {link._physx_pointer: side
                      for side, robot in backend.robots.items()
                      for link in robot.get_links()}
            owners.update({link._physx_pointer: "gamepad" for link in art.get_links()})
            pad_states.append(dict(sleeping=bool(art.get_links()[0].sleeping),
                actual_timestep_s=float(backend.scene.timestep),
                art_iterations=[art.get_solver_position_iterations(), art.get_solver_velocity_iterations()],
                solver_policy=asdict(backend.gamepad.solver_policy),
                always_awake=awake_record if a.always_awake else None,
                sleep_threshold=art.get_sleep_threshold(), qf=art.get_qf().tolist(),
                qpos=art.get_qpos().tolist(), qvel=art.get_qvel().tolist(),
                robot_dof={side:len(robot.get_qpos()) for side,robot in backend.robots.items()},
                contact_bodies=[[body.entity.name for body in contact.bodies]
                                for contact in backend.scene.get_contacts()],
                contact_owners=[[owners.get(body._physx_pointer, "fixture")
                                 for body in contact.bodies]
                                for contact in backend.scene.get_contacts()]))
            return original_close()

        backend.close = close
        return backend

    from experiments.robotwin.station_rtf.overrides import policy
    with patch.object(collection, "create_backend", side_effect=factory), \
         patch.object(aq, "TimedScene", PerStepScene), aq.policy(a.variant), \
         policy(sleep_threshold=a.sleep_threshold, batch_size=a.batch_size,
                batch_library=a.batch_library) as batch_records:
        result = aq.bench(a.output, a.variant, a.steps, a.repetitions, True,
                          "full", a.condition == "active", False,
                          a.iterations, None, a.condition == "contact")
    distribution = {}
    arrays = {}
    for name, repetitions in [("native", native_arrays), ("total", total_arrays)]:
        trials = []
        for i, samples in enumerate(repetitions):
            values = np.asarray(samples[-a.steps:], dtype=np.int64)
            arrays[f"{name}_{i}_ns"] = values
            trials.append(dict(median_us=float(np.median(values)/1000),
                               p95_us=float(np.percentile(values, 95)/1000),
                               max_us=float(np.max(values)/1000),
                               over_800us_steps=int(np.count_nonzero(values > 800_000)),
                               measured_steps=len(values),
                               mean_us=float(np.mean(values)/1000)))
        distribution[name] = dict(trials=trials,
            median_us=float(np.median([r["median_us"] for r in trials])),
            p95_us=float(np.median([r["p95_us"] for r in trials])),
            max_us=max(r["max_us"] for r in trials),
            over_800us_steps=sum(r["over_800us_steps"] for r in trials),
            measured_steps=sum(r["measured_steps"] for r in trials),
            median_range_us=[min(r["median_us"] for r in trials), max(r["median_us"] for r in trials)],
            p95_range_us=[min(r["p95_us"] for r in trials), max(r["p95_us"] for r in trials)])
    np.savez_compressed(a.output/"step_times.npz", **arrays)
    receipt = dict(result=result, distribution=distribution, pad_states=pad_states,
        batch_records=batch_records,
        versions={n: importlib.metadata.version(n) for n in ["sapien", "xbox-gamepad-physics"]},
        provenance=dict(aq_probe_sha256=hashlib.sha256(a.aq_probe.read_bytes()).hexdigest(),
            script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            python=platform.python_version(), cpu_affinity=sorted(os.sched_getaffinity(0)),
            cpu_workers=0, omp_threads=os.environ.get("OMP_NUM_THREADS"),
            openblas_threads=os.environ.get("OPENBLAS_NUM_THREADS"), cuda=os.environ.get("CUDA_VISIBLE_DEVICES"),
            manifest_sha256=hashlib.sha256((Path(os.environ["XBOX_GAMEPAD_PHYSICS_RESOURCES"])/"robotwin/full_controls/manifest.json").read_bytes()).hexdigest(),
            step_times_sha256=hashlib.sha256((a.output/"step_times.npz").read_bytes()).hexdigest()))
    (a.output/"summary.json").write_text(json.dumps(receipt, indent=2)+"\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
