"""Fixed 10/1 attribution; delegates unchanged T4 protocol and scorer."""
import argparse
import copy
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch


@contextmanager
def fixed_iterations():
    import xbox_gamepad_physics.robotwin.loader as loader
    original = loader._validated_description

    def description(*args, **kwargs):
        d = original(*args, **kwargs)
        if not hasattr(d, 'backend_options'):
            return d
        opts = copy.deepcopy(d.backend_options)
        if 'solver_iterations' in opts:
            for name, count in [('position', 10), ('velocity', 1)]:
                opts['solver_iterations'][name]['value'] = count
        return replace(d, backend_options=opts)

    with patch.object(loader, '_validated_description', side_effect=description):
        yield


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--resources', type=Path, required=True)
    p.add_argument('--old-source', type=Path)
    a = p.parse_args()
    if a.old_source:
        sys.path.insert(0, str(a.old_source.resolve()))
    os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES'] = str(a.resources.resolve())
    import sapien
    import xbox_gamepad_physics
    from tests.acceptance.robotwin import executor, run_suite
    sapien.physx.set_scene_config(cpu_workers=0, enable_tgs=True)
    a.output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    receipts = []
    original_setup = executor.RobotwinPressExecutor.setup
    def setup(e, *args, **kwargs):
        original_setup(e, *args, **kwargs)
        # Every independent articulation is forced to 10/1 before any simulation.
        e.art.set_solver_position_iterations(10)
        e.art.set_solver_velocity_iterations(1)
        receipts.append(dict(iterations=[e.art.get_solver_position_iterations(),e.art.get_solver_velocity_iterations()], dt=e.dt, qf=e.art.get_qf().tolist(), joints={j.name:dict(K=j.stiffness,D=j.damping,friction=j.get_friction(),cap=j.force_limit,target=j.get_drive_target().tolist()) for j in e.art.get_active_joints()}))
    with fixed_iterations(), patch.object(executor.RobotwinPressExecutor,'setup',setup), patch.object(executor,'create_scene',side_effect=run_suite.cpu_scene):
        run_suite.run(a.resources, a.output/'T4', cases=['View','Menu','Guide','A'], iterations=(10,1), collect_all=True)
    summary = dict(versions={n:importlib.metadata.version(n) for n in ['sapien','xbox-gamepad-physics']}, package_file=xbox_gamepad_physics.__file__,resources=str(a.resources),cpu_affinity=sorted(os.sched_getaffinity(0)),cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'),display=os.environ.get('DISPLAY'),elapsed_s=time.monotonic()-start,receipts=receipts,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    summary['T4']=[r for r in json.loads((a.output/'T4/results.json').read_text())['results'] if r['status']!='not_run']
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='receipts'}),flush=True)

if __name__=='__main__':
    main()
