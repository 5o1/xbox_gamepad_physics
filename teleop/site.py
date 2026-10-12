"""Private site settings shared by shell launchers and Python tools."""
import os
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'configs/teleop_site.example.env'


def settings(path=None):
    path = Path(path or os.environ.get('TELEOP_SITE_CONFIG', ROOT / 'configs/local/teleop_site.env'))
    result = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            tokens = shlex.split(line, comments=True)
            if not tokens:
                continue
            if len(tokens) != 1 or '=' not in tokens[0]:
                raise ValueError(f'{path}: expected shell-quoted KEY=value')
            key, value = tokens[0].split('=', 1)
            if not key.startswith('TELEOP_'):
                raise ValueError(f'{path}: expected TELEOP_ setting')
            result[key] = os.path.expanduser(os.path.expandvars(value))
    result.update({k:v for k,v in os.environ.items() if k.startswith('TELEOP_')})
    return result


def require(key):
    value = settings().get(key)
    if not value or '<' in value or '>' in value:
        raise ValueError(f'Missing local setting {key}; copy and fill {TEMPLATE} into configs/local/teleop_site.env')
    return value


def profile_command(command):
    return [require('TELEOP_LOGIN_PROFILE'), '--wohint', '-n', '-o', 'BatchMode=yes', command]


def browser_url():
    return f"http://127.0.0.1:{require('TELEOP_WSL_PORT')}/"


def resolve_config(cfg):
    if not cfg['teleop'].get('robotwin_root'):
        cfg['teleop']['robotwin_root'] = require('TELEOP_ROBOTWIN_ROOT')
    return cfg


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--shell', action='store_true')
    args = p.parse_args()
    # Export only settings; never evaluate commands from the config in Python.
    for key, value in settings().items():
        print(f'export {key}={shlex.quote(value)}')
