"""Detached remote session ownership and checked cleanup, using only stdlib."""
from pathlib import Path
import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

RECEIPT='session_processes.json'


def identity(pid):
    proc=Path('/proc')/str(pid)
    try:
        fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
        if fields[0]=='Z':return None
        return {'pid':pid,'start_ticks':int(fields[19]),
                'argv':(proc/'cmdline').read_bytes().decode(errors='replace')}
    except FileNotFoundError:return None


def stable_identity(pid, timeout=2.0):
    # /proc/<pid>/cmdline can read empty for a moment around exec under load;
    # recording that would make cleanup refuse to signal the live process.
    deadline=time.monotonic()+timeout
    value=identity(pid)
    while value is not None and not value['argv'] and time.monotonic()<deadline:
        time.sleep(.02);value=identity(pid)
    return value


def record_processes(run, port, pids):
    run=Path(run)
    rows=[value for pid in pids if (value:=stable_identity(pid)) is not None]
    data={'run':run.name,'output':str(run.resolve()),'port':port,'processes':rows}
    temporary=run/(RECEIPT+'.tmp')
    temporary.write_text(json.dumps(data,indent=2)+'\n')
    temporary.replace(run/RECEIPT)
    return data


def launch(run, command):
    run=Path(run).expanduser().resolve()
    if run.exists():raise FileExistsError('session output already exists: '+str(run))
    run.parent.mkdir(parents=True,exist_ok=True)
    # Capture errors before the gateway creates its directory and redirects fds.
    with tempfile.NamedTemporaryFile(prefix=run.name+'-',suffix='-bootstrap.log',dir=run.parent,delete=False) as log:
        bootstrap=Path(log.name)
        child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                               start_new_session=True,close_fds=True)
    deadline=time.monotonic()+10
    while not (run/RECEIPT).is_file():
        if child.poll() is not None:
            raise RuntimeError('remote gateway exited before ownership receipt: '+bootstrap.read_text(errors='replace'))
        if time.monotonic()>deadline:
            # The exact Popen handle belongs to this launch, not an arbitrary PID.
            child.terminate();child.wait(timeout=5)
            raise TimeoutError('remote gateway did not create ownership receipt; see '+str(bootstrap))
        time.sleep(.02)
    return {'run':run.name,'gateway_pid':child.pid,'bootstrap_log':str(bootstrap),
            'gateway_log':str(run/'gateway.log')}


def remaining(run):
    run=Path(run).expanduser().resolve()
    data=json.loads((run/RECEIPT).read_text())
    if data['output']!=str(run) or data['run']!=run.name:raise ValueError('session receipt identity mismatch')
    alive=[];changed=[]
    for expected in data['processes']:
        current=identity(expected['pid'])
        if current is None:continue
        if current!=expected:
            changed.append(expected['pid'])
            if current['start_ticks']!=expected['start_ticks']:continue
            # Same kernel process is still alive; uncertain argv is not exit proof.
            alive.append(expected);continue
        alive.append(current)
    return data,alive,changed


def cleanup(run, *, shutdown=False, wait=40):
    run=Path(run).expanduser().resolve()
    data,alive,changed=remaining(run)
    response={'attempted':False,'status':None,'error':None}
    if shutdown and alive:
        response['attempted']=True
        url=f'http://127.0.0.1:{data["port"]}/shutdown?run={run.name}'
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(urllib.request.Request(url,method='POST'),timeout=5) as result:
                response['status']=result.status
                if result.status!=200:response['error']='non-200 shutdown response'
        except OSError as error:
            response['status']=getattr(error,'code',None);response['error']=str(error)
    deadline=time.monotonic()+wait
    while alive and time.monotonic()<deadline:
        time.sleep(.1);data,alive,changed=remaining(run)
    forced=[]
    for sig,grace in ((signal.SIGTERM,5),(signal.SIGKILL,2)):
        if not alive:break
        signalled=False
        for expected in alive:
            # Recheck creation time and argv immediately before any signal.
            if identity(expected['pid'])!=expected:continue
            try:os.kill(expected['pid'],sig)
            except ProcessLookupError:continue
            forced.append({'pid':expected['pid'],'signal':sig.name});signalled=True
        if not signalled:break
        deadline=time.monotonic()+grace
        while alive and time.monotonic()<deadline:
            time.sleep(.1);data,alive,changed=remaining(run)
    reason=run/'stop_reason.json';reason_value=None;reason_error=None
    try:
        if reason.exists():reason_value=json.loads(reason.read_text())
    except (OSError,ValueError) as error:reason_error=str(error)
    return {'run':run.name,'all_exited':not alive,'remaining_pids':[p['pid'] for p in alive],
            'shutdown':response,'forced_cleanup':forced,'identity_changed_not_signalled':changed,
            'stop_reason':reason_value,'stop_reason_error':reason_error}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('start','cleanup'))
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--shutdown',action='store_true')
    parser.add_argument('--wait',type=float,default=40)
    args,command=parser.parse_known_args()
    if args.action=='start':
        if command[:1]==['--']:command=command[1:]
        value=launch(args.run,command)
    else:
        if command:parser.error('unexpected cleanup arguments')
        value=cleanup(args.run,shutdown=args.shutdown,wait=args.wait)
    print(json.dumps(value),flush=True)
    if args.action=='cleanup' and (not value['all_exited'] or value['shutdown']['error']):return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
