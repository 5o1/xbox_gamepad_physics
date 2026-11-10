"""Verify site-packages payload bytes before running release acceptance."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import zipfile


def review(wheel, backend, output):
    import xbox_gamepad_physics as package
    from xbox_gamepad_physics.resources import package_version

    origin = Path(package.__file__).resolve()
    prefix = Path(sys.prefix).resolve()
    distribution = importlib.metadata.distribution('xbox-gamepad-physics')
    with zipfile.ZipFile(wheel) as archive:
        members = [name for name in archive.namelist()
                   if name.startswith('xbox_gamepad_physics/') and not name.endswith('/')]
        mismatches = [name for name in members
                      if not Path(distribution.locate_file(name)).is_file()
                      or Path(distribution.locate_file(name)).read_bytes() != archive.read(name)]
    source_shadowing = not origin.is_relative_to(prefix)
    result = {
        'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
        'package_version': distribution.version, 'runtime_version': package_version(),
        'python_version': sys.version.split()[0],
        'engine_version': importlib.metadata.version('sapien' if backend == 'robotwin' else backend),
        'package_file': '$NODE_ENVS/' + prefix.name + '/' + str(origin.relative_to(prefix)),
        'source_shadowing': source_shadowing,
        'payload_files_compared': len(members), 'payload_mismatches': mismatches,
        'cpu_affinity': sorted(os.sched_getaffinity(0)),
        'display': os.environ.get('DISPLAY'),
        'cuda_visible_devices': os.environ.get('CUDA_VISIBLE_DEVICES'),
        'qa_pythonpath_has_package_src': any(
            (Path(folder) / 'xbox_gamepad_physics').is_dir()
            for folder in os.environ.get('PYTHONPATH', '').split(os.pathsep) if folder),
    }
    result['passed'] = (not source_shadowing and not mismatches
                        and result['runtime_version'] == distribution.version == '0.4.3'
                        and not result['qa_pythonpath_has_package_src'])
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return result['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--backend', choices=('robotwin', 'mujoco'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(not review(args.wheel, args.backend, args.output))
