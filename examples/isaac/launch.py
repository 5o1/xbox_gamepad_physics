"""Launch a preview using the project's existing private site configuration."""
import argparse
import os
from pathlib import Path
import subprocess

from xbox_gamepad_physics.teleop.site import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-config', type=Path, required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    config = settings(args.site_config)

    def required(key):
        value = config.get(key)
        if not value or '<' in value or '>' in value:
            parser.error(f'Set {key} in the private site configuration')
        return value

    environment = os.environ.copy()
    environment.update(config)
    environment['TELEOP_SITE_CONFIG'] = str(args.site_config.resolve())
    library = required('TELEOP_ISAAC_LIBRARY_ROOT')
    environment['LD_LIBRARY_PATH'] = library + (
        os.pathsep + environment['LD_LIBRARY_PATH']
        if environment.get('LD_LIBRARY_PATH') else '')
    environment['CUDA_VISIBLE_DEVICES'] = required('TELEOP_GPU')
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    command = [required('TELEOP_ISAAC_PYTHON'),
               str(Path(__file__).with_name('load_and_read.py')),
               '--resources', required('TELEOP_RESOURCE_ROOT'),
               '--output', required('TELEOP_LOCAL_OUTPUT'), *arguments]
    return subprocess.run(command, env=environment).returncode


if __name__ == '__main__':
    raise SystemExit(main())
