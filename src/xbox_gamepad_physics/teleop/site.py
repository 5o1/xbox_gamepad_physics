"""Private site settings shared by shell launchers and Python tools."""
import os
from pathlib import Path
import shlex
import time
import datetime
import signal
import socket

from xbox_gamepad_physics.resources import _repository
ROOT = _repository() or Path.cwd()
TEMPLATE = Path(__file__).with_name('templates') / 'teleop_site.example.env'
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


def local_port_owners(port):
    """Linux listener inode -> PID, command and kernel start time; no dependency."""
    port=int(port);inodes=set()
    for name in ('tcp','tcp6'):
        path=Path('/proc/net')/name
        if not path.exists():continue
        for line in path.read_text().splitlines()[1:]:
            fields=line.split()
            if fields[3]=='0A' and int(fields[1].rsplit(':',1)[1],16)==port:inodes.add(fields[9])
    owners=[]
    if not inodes:return owners
    boot=next(int(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime '))
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            sockets=set()
            for fd in (proc/'fd').iterdir():
                try:sockets.add(fd.readlink().name)
                except OSError:continue  # descriptor may close during enumeration
            if not any(f'socket:[{inode}]' in sockets for inode in inodes):continue
            argv=(proc/'cmdline').read_bytes().rstrip(b'\0').decode(errors='replace').split('\0')
            stat=(proc/'stat').read_text().rsplit(')',1)[1].split();ticks=int(stat[19])
            # Read only project markers from environ; never print environment data.
            marks={}
            for item in (proc/'environ').read_bytes().split(b'\0'):
                key,_,value=item.partition(b'=')
                if key in (b'TELEOP_TUNNEL_PROJECT',b'TELEOP_SITE_CONFIG'):marks[key.decode()]=value.decode(errors='replace')
            owners.append({'pid':int(proc.name),'argv':argv,'command':shlex.join(argv),
                'start_ticks':ticks,'started':datetime.datetime.fromtimestamp(boot+ticks/os.sysconf('SC_CLK_TCK')).astimezone().isoformat(),
                'exe':str((proc/'exe').readlink()),'cwd':str((proc/'cwd').readlink()),'markers':marks,
                'uid':proc.stat().st_uid})
        except (OSError,ValueError,IndexError):continue
    return owners


def is_project_tunnel(owner,port,cfg):
    """Require ssh, exact forwarding/auth endpoint and evidence of this checkout."""
    argv=owner['argv']
    if Path(owner['exe']).name!='ssh' or owner['uid']!=os.getuid():return False
    def option(name):
        for index,word in enumerate(argv):
            if word==name and index+1<len(argv):return argv[index+1]
            if word.startswith(name) and len(word)>len(name):return word[len(name):]
        return None
    forwarding=option('-L')
    accepted={f'0.0.0.0:{port}:127.0.0.1:{cfg["TELEOP_REMOTE_PORT"]}',
              f'127.0.0.1:{port}:127.0.0.1:{cfg["TELEOP_REMOTE_PORT"]}'}
    if forwarding not in accepted:return False
    if cfg.get('TELEOP_SSH_ALIAS'):
        if cfg['TELEOP_SSH_ALIAS'] not in argv:return False
        if cfg.get('TELEOP_SSH_PORT') and option('-p')!=str(cfg['TELEOP_SSH_PORT']):return False
        if cfg.get('TELEOP_SSH_IDENTITY'):
            identity=option('-i')
            if not identity or Path(identity).expanduser().resolve()!=Path(cfg['TELEOP_SSH_IDENTITY']).resolve():return False
    else:
        if cfg['TELEOP_SSH_USER']+'@'+cfg['TELEOP_GPU_HOST'] not in argv:return False
        if option('-p')!=cfg['TELEOP_SSH_PORT']:return False
        identity=option('-i')
        if not identity or Path(identity).expanduser().resolve()!=Path(cfg['TELEOP_SSH_IDENTITY']).resolve():return False
    if not argv[-1].startswith('cat >/dev/null'):return False
    marks=owner['markers']
    project=str(ROOT.resolve())
    if marks.get('TELEOP_TUNNEL_PROJECT'):
        return Path(marks['TELEOP_TUNNEL_PROJECT']).resolve()==ROOT.resolve()
    # Legacy A–F tunnel: same complete endpoint plus project cwd/site evidence.
    site=marks.get('TELEOP_SITE_CONFIG')
    return Path(owner['cwd']).resolve()==ROOT.resolve() or bool(site and Path(site).resolve().is_relative_to(ROOT.resolve()))


def check_local_port(port,cfg,stop_existing=False,emit=print):
    """Never terminate an unconfirmed listener. Recheck identity before SIGTERM."""
    owners=local_port_owners(port)
    if not owners:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:probe.bind(('0.0.0.0',int(port)))
            except OSError:raise ValueError(f'Local port {port} is occupied but its owning PID cannot be identified; refusing to start') from None
        return []
    for owner in owners:emit(f'Local port {port}: PID {owner["pid"]}, started {owner["started"]}, command {owner["command"]}')
    if not stop_existing:raise ValueError(f'Local port {port} is occupied; the default keeps the process running. Use --stop-existing after confirming it is an old project tunnel')
    if not all(is_project_tunnel(owner,port,cfg) for owner in owners):
        raise ValueError(f'Local port {port} is occupied by a non-project tunnel or an unverified process; refusing to stop it or start')
    for owner in owners:
        current=next((o for o in local_port_owners(port) if o['pid']==owner['pid']),None)
        if current is None:continue
        if current['start_ticks']!=owner['start_ticks'] or not is_project_tunnel(current,port,cfg):
            raise ValueError('The port owner has changed; refusing to terminate the old PID')
        os.kill(owner['pid'],signal.SIGTERM)
        emit(f'Sent SIGTERM to verified old project tunnel PID {owner["pid"]}.')
    deadline=time.monotonic()+5
    while local_port_owners(port):
        if time.monotonic()>=deadline:raise ValueError(f'The old tunnel did not release local port {port} within 5 s; refusing to start')
        time.sleep(.05)
    return owners


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--shell', action='store_true')
    p.add_argument('--check-local-port',type=int)
    p.add_argument('--stop-existing',action='store_true')
    args = p.parse_args()
    # Export only settings; never evaluate commands from the config in Python.
    try:
        values=settings()
        if args.check_local_port is not None:
            check_local_port(args.check_local_port,values,args.stop_existing)
    except ValueError as error:
        p.error(str(error))
    if args.shell:
        for key, value in values.items():print(f'export {key}={shlex.quote(value)}')
