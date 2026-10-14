from .site import require, browser_url, profile_command
import shlex
"""Three ordinary login-shell trials from HOME/base, including Windows health."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import termios
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument("--trials",type=int,default=1)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    trials=[]
    for index in range(1,args.trials+1):
        master,slave=pty.openpty()
        def terminal():
            os.setsid();fcntl.ioctl(slave,termios.TIOCSCTTY,0)
        # No run-name/GPU overrides: exercise the exact default that failed.
        command=f'source {shlex.quote(require("TELEOP_CONDA_INIT"))}; conda activate base; cd "$HOME"; printf "cwd=%s conda=%s ssh=%s\\n" "$PWD" "$CONDA_DEFAULT_ENV" "$(command -v ssh)"; exec bash {shlex.quote(str(ROOT/"scripts/teleop_session.sh"))}'
        child=subprocess.Popen(['bash','-lc',command],stdin=slave,stdout=slave,stderr=slave,preexec_fn=terminal)
        os.close(slave);output=bytearray();deadline=time.monotonic()+90
        try:
            while 'Open in the Windows browser'.encode() not in output:
                if time.monotonic()>deadline:raise TimeoutError('launcher did not print browser address')
                if select.select([master],[],[],.5)[0]:
                    try:data=os.read(master,65536)
                    except OSError:data=b''
                    if not data:raise RuntimeError(f'launcher exited {child.poll()}: {output.decode(errors="replace")}')
                    output.extend(data)
            health=json.loads(subprocess.check_output(['curl','--noproxy','*','-fsS',browser_url()+'health'],text=True))
            win=subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-Command',
                f"curl.exe --noproxy '*' --fail --silent --show-error http://localhost:{require('TELEOP_PORT')}/health"],text=True).strip()
            windows=json.loads(win)
            if not health['ready'] or not windows['ready']:raise RuntimeError('health not ready')
            os.write(master,b'\x03') # real terminal Ctrl+C, not a detached process kill
            child.wait(timeout=20)
            while select.select([master],[],[],.1)[0]:
                try:data=os.read(master,65536)
                except OSError:break
                if not data:break
                output.extend(data)
            probe='ps -eo pid,args | grep -E "python.* -m teleop|ffmpeg.*h264" | grep -v grep || true'
            time.sleep(.5)
            remaining=subprocess.check_output(profile_command(probe),text=True).strip()
            if remaining:raise RuntimeError('session left workers: '+remaining)
            trials.append({'trial':index,'cwd':str(Path.home()),'conda':'base','default_run_name':True,
                           'health':health,'windows_health':windows,'launcher_exit':child.returncode,'remaining_workers':remaining})
            print(json.dumps(trials[-1]),flush=True)
        finally:
            if child.poll() is None:
                os.write(master,b'\x03');child.wait(timeout=20)
            os.close(master)
            (args.output/f'launch{index}.log').write_bytes(output)
            (args.output/'launch_trials.json').write_text(json.dumps(trials,indent=2))


if __name__=='__main__':main()
