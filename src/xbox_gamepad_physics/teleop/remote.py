"""Explicit OpenSSH transport; GPU processes use the preinstalled wheel."""
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from .site import settings, check_local_port, tunnel_keepalive, validate_tunnel_timeout, ROOT

PORT_CHECK = '''import json,socket,sys,time,urllib.request,urllib.parse
port,stop=int(sys.argv[1]),bool(int(sys.argv[2]))
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def occupied():
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=1):return True
    except ConnectionRefusedError:return False
if occupied():
    try:
        with opener.open(f'http://127.0.0.1:{port}/health',timeout=3) as r:h=json.load(r)
        assert isinstance(h.get('run'),str) and 'physics_alive' in h
    except Exception as e:raise SystemExit(f'Port {port} is occupied by an unverified teleop session; refusing to stop it: {e}')
    print(f'Port {port} is occupied by session {h["run"]}',flush=True)
    if not stop:raise SystemExit('The default keeps the existing session running; use --stop-existing after confirming its identity')
    url=f'http://127.0.0.1:{port}/shutdown?'+urllib.parse.urlencode({'run':h['run']})
    opener.open(urllib.request.Request(url,method='POST'),timeout=5).close()
    deadline=time.monotonic()+40
    while occupied():
        if time.monotonic()>deadline:raise SystemExit('The previous session has not exited; refusing to start')
        time.sleep(.25)
'''


def _available(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1',int(port)))


def run(args):
    cfg=settings(args.site) if args.site else {}
    def value(name,key=None,default=None):
        v=getattr(args,name,None)
        if v is not None:return v
        v=cfg.get(key) if key else None
        if v and ('<' in v or '>' in v):raise ValueError('Please provide '+key)
        return v if v not in (None,'') else default
    robotwin=value('robotwin_root','TELEOP_ROBOTWIN_ROOT')
    resources=value('resources','TELEOP_RESOURCE_ROOT')
    gpu=value('gpu','TELEOP_GPU')
    output=value('output')
    if output is None and cfg.get('TELEOP_REMOTE_ROOT'):
        name=os.environ.get('TELEOP_RUN_NAME') or time.strftime('live-%Y%m%d-%H%M%S')
        if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):raise ValueError('Invalid session name')
        output=cfg['TELEOP_REMOTE_ROOT'].rstrip('/')+'/'+name
    remote_python=value('remote_python','TELEOP_STREAM_PYTHON')
    simulation_python=value('simulation_python','TELEOP_BASE_PYTHON',remote_python)
    for name,v in [('robotwin-root',robotwin),('resources',resources),('gpu',gpu),('output',output),('remote-python',remote_python)]:
        if v is None:raise ValueError('remote requires --'+name+' or an explicit --site configuration')
    port=int(value('port','TELEOP_REMOTE_PORT',8775));local_port=int(value('local_port','TELEOP_LOCAL_PORT',cfg.get('TELEOP_WSL_PORT',port)))
    windows=(args.windows_relay or bool(args.site and cfg.get('TELEOP_WSL_INTERFACE'))) and not getattr(args,'skip_windows_relay',False)
    relay_port=int(value('relay_port','TELEOP_PORT',local_port))
    timeout=validate_tunnel_timeout(value('tunnel_timeout_s','TELEOP_TUNNEL_TIMEOUT_S',60))
    interval,count=tunnel_keepalive(timeout)
    alias=args.ssh or cfg.get('TELEOP_SSH_ALIAS')
    destination=alias or (cfg.get('TELEOP_SSH_USER','')+'@'+cfg.get('TELEOP_GPU_HOST',''))
    if not destination or destination=='@' or '<' in destination:raise ValueError('remote requires --ssh alias or a complete site SSH configuration')
    identity=value('identity','TELEOP_SSH_IDENTITY');ssh_port=value('ssh_port','TELEOP_SSH_PORT')
    ssh=['ssh','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes']
    if identity:ssh+=['-i',str(Path(identity).expanduser()),'-o','IdentitiesOnly=yes','-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no','-o','PreferredAuthentications=publickey']
    if ssh_port:ssh+=['-p',str(ssh_port)]
    profile=cfg.get('TELEOP_LOGIN_PROFILE')
    transport=[profile,'--wohint','-n','-o','BatchMode=yes'] if profile else [*ssh,'-n',destination]
    # G's process identification is only used in this explicit remote branch.
    tunnel_cfg=dict(cfg,TELEOP_REMOTE_PORT=str(port))
    if alias:tunnel_cfg['TELEOP_SSH_ALIAS']=alias
    if identity:tunnel_cfg['TELEOP_SSH_IDENTITY']=str(identity)
    if ssh_port:tunnel_cfg['TELEOP_SSH_PORT']=str(ssh_port)
    check_local_port(local_port,tunnel_cfg,args.stop_existing)
    if windows:_available(relay_port)
    subprocess.run([*transport,shlex.join([str(remote_python),'-c',PORT_CHECK,str(port),str(int(args.stop_existing))])],check=True)
    from xbox_gamepad_physics.resources import package_version
    check_version='from importlib.metadata import version; import sys; assert version("xbox-gamepad-physics")==sys.argv[1], "remote wheel version mismatch"'
    subprocess.run([*transport,shlex.join([str(remote_python),'-c',check_version,package_version()])],check=True)
    command=[str(remote_python),'-u','-m','xbox_gamepad_physics','teleop','--mode','local',
             '--robotwin-root',str(robotwin),'--resources',str(resources),'--output',str(output),
             '--gpu',str(gpu),'--port',str(port),'--collision',args.collision,
             '--render-candidate',args.render_candidate,'--tunnel-timeout-s',str(timeout),
             '--simulation-python',str(simulation_python),'--log-to-file']
    if args.config:command+=['--config',str(args.config)]
    logroot=Path(value('local_output','TELEOP_LOCAL_OUTPUT',Path.cwd()/'teleop-logs')).expanduser().resolve()
    logroot.mkdir(parents=True,exist_ok=True)
    run_name=Path(output).name
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    processes=[];streams=[];writer=None;fifo=None;launched=False
    lost_transport=False;remote_ended=False;return_code=0
    def terminate(*_):raise KeyboardInterrupt
    old={sig:signal.signal(sig,terminate) for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
    try:
        start=[str(remote_python),'-m','xbox_gamepad_physics.teleop.remote_session','start',
               '--run',str(output),'--',*command]
        response=subprocess.run([*transport,shlex.join(start)],capture_output=True,text=True,timeout=20)
        if response.returncode:
            raise RuntimeError('Remote startup failed: '+response.stdout+response.stderr)
        started=json.loads(response.stdout)
        if started['run']!=run_name:raise RuntimeError('remote launch returned a different run')
        launched=True
        (logroot/(run_name+'-launch.json')).write_text(json.dumps(started,indent=2)+'\n')
        # G: only this parent owns the FIFO writer; child descriptors are not inherited.
        fd,path=tempfile.mkstemp(prefix=run_name+'-',suffix='.fifo',dir=logroot)
        os.close(fd);os.unlink(path);fifo=Path(path);os.mkfifo(fifo)
        shell=shlex.join([*ssh,'-T','-o',f'ServerAliveInterval={interval}',
                         '-o',f'ServerAliveCountMax={count}',
                         '-L',f'{"0.0.0.0" if windows else "127.0.0.1"}:{local_port}:127.0.0.1:{port}',
                         destination,'cat >/dev/null'])+' < '+shlex.quote(str(fifo))
        log=(logroot/(run_name+'-tunnel.log')).open('w');streams.append(log)
        env=dict(os.environ,TELEOP_TUNNEL_PROJECT=str(ROOT.resolve()))
        tunnel=subprocess.Popen(['bash','-c','exec '+shell],stdout=log,stderr=subprocess.STDOUT,env=env)
        processes.append(tunnel);writer=fifo.open('w')
        if windows:
            interface=value('wsl_interface','TELEOP_WSL_INTERFACE')
            if not interface:raise ValueError('Windows relay requires --wsl-interface')
            rows=subprocess.check_output(['ip','-4','-o','address','show','dev',interface],text=True).split()
            address=rows[rows.index('inet')+1].split('/')[0]
            script=subprocess.check_output(['wslpath','-w',str(Path(__file__).with_name('windows_relay.ps1'))],text=True).strip()
            ps="& ([scriptblock]::Create((Get-Content -Raw '"+script.replace("'","''")+"'))) -ListenPort "+str(relay_port)+" -WslAddress '"+address+"' -WslPort "+str(local_port)
            log=(logroot/(run_name+'-relay.log')).open('w');streams.append(log)
            processes.append(subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-Command',ps],stdout=log,stderr=subprocess.STDOUT))
        url=f'http://127.0.0.1:{local_port}/'
        def health():
            with opener.open(url+'health',timeout=2) as result:return json.load(result)
        deadline=time.monotonic()+120
        while True:
            if any(proc.poll() is not None for proc in processes):
                lost_transport=True;raise RuntimeError('Tunnel or relay exited early; see '+str(logroot))
            try:
                status=health()
                if status.get('ready') and status.get('run')==run_name:break
            except OSError:pass
            if time.monotonic()>deadline:raise TimeoutError('Remote health was not ready within 120 seconds; see '+str(logroot))
            time.sleep(.2)
        browser_url=f'http://localhost:{relay_port}/' if windows else url
        print(('Open in the Windows browser ' if windows else 'Teleop remote ready ')+browser_url+' (Ctrl+C stops this session)',flush=True)
        if args.open_browser:
            import webbrowser
            webbrowser.open(browser_url)
        while True:
            if any(proc.poll() is not None for proc in processes):
                lost_transport=True;return_code=2;break
            try:health()
            except OSError:remote_ended=True;break
            time.sleep(.3)
    except KeyboardInterrupt:
        pass
    finally:
        for sig,handler in old.items():signal.signal(sig,handler)
        if writer is not None:writer.close()
        for proc in processes:
            if proc.poll() is None:proc.terminate()
        for proc in processes:
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        if fifo is not None:fifo.unlink(missing_ok=True)
        for stream in streams:stream.close()
        if launched:
            wait=timeout+5 if lost_transport else 3 if remote_ended else 40
            cleanup=[str(remote_python),'-m','xbox_gamepad_physics.teleop.remote_session','cleanup',
                     '--run',str(output),'--wait',str(wait)]
            if not lost_transport and not remote_ended:cleanup.append('--shutdown')
            try:
                response=subprocess.run([*transport,shlex.join(cleanup)],capture_output=True,
                                        text=True,timeout=wait+15)
                if response.stdout.strip():
                    status=json.loads(response.stdout)
                    (logroot/(run_name+'-cleanup.json')).write_text(json.dumps(status,indent=2)+'\n')
                    print('remote cleanup '+json.dumps(status),flush=True)
                    if status.get('forced_cleanup'):
                        print('This session did not exit on its own; cleaned up using the recorded process identity.',file=sys.stderr)
                        return_code=2
                if response.returncode:
                    print('Remote shutdown/cleanup failed (nonzero exit or non-200 response): '+response.stdout+response.stderr,file=sys.stderr)
                    return_code=2
            except (OSError,subprocess.TimeoutExpired,ValueError) as error:
                print('Unable to confirm that the remote session has exited: '+str(error),file=sys.stderr)
                return_code=2
    return return_code
