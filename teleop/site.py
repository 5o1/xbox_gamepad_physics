"""Private site settings shared by shell launchers and Python tools."""
import os
from pathlib import Path
import shlex
import time

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'configs/teleop_site.example.env'
# Communication test settings, not physical parameters; owner may adjust them.
TUNNEL_TIMEOUT_DEFAULT_S = 60
TUNNEL_TIMEOUT_MIN_S = 10
TUNNEL_TIMEOUT_MAX_S = 300


def validate_tunnel_timeout(value):
    """Integer seconds shared by OpenSSH keepalive and the session watchdog."""
    try:
        timeout=int(str(value))
    except (ValueError,TypeError):
        raise ValueError(f'TELEOP_TUNNEL_TIMEOUT_S must be integer seconds in {TUNNEL_TIMEOUT_MIN_S}–{TUNNEL_TIMEOUT_MAX_S}; got {value!r}') from None
    if not TUNNEL_TIMEOUT_MIN_S<=timeout<=TUNNEL_TIMEOUT_MAX_S:
        raise ValueError(f'TELEOP_TUNNEL_TIMEOUT_S allowed range {TUNNEL_TIMEOUT_MIN_S}–{TUNNEL_TIMEOUT_MAX_S} s; got {timeout}')
    return timeout


def tunnel_keepalive(timeout):
    timeout=validate_tunnel_timeout(timeout)
    count=next(n for n in (3,2,1) if timeout%n==0)
    return timeout//count,count


def tunnel_timeout_argument(value):
    """Keep the allowed-range diagnostic when argparse handles invalid input."""
    import argparse
    try:return validate_tunnel_timeout(value)
    except ValueError as error:raise argparse.ArgumentTypeError(str(error)) from None


class IdleWatchdog:
    """Messages and disconnects reset the same window; connecting alone does not.

    A reconnect with a message continues the same session. This is independent
    of the 0.2 s input lease; it only requests session termination on expiry.
    """
    def __init__(self,timeout,clock=time.monotonic):
        self.timeout=validate_tunnel_timeout(timeout);self.clock=clock
        self.started=self.last_activity=clock();self.last_kind='session-start'
    def activity(self,kind='control-message'):
        self.last_activity=self.clock();self.last_kind=kind
    def expired(self):return self.clock()-self.last_activity>=self.timeout


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
    result['TELEOP_TUNNEL_TIMEOUT_S']=str(validate_tunnel_timeout(result.get('TELEOP_TUNNEL_TIMEOUT_S',TUNNEL_TIMEOUT_DEFAULT_S)))
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
    try:
        values=settings()
    except ValueError as error:
        p.error(str(error))
    for key, value in values.items():
        print(f'export {key}={shlex.quote(value)}')
