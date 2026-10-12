from .site import require, browser_url, profile_command
import shlex
"""One isolated 60-second window, with local/GPU load snapshots on both sides."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .load_probe import probe


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--idle',action='store_true')
    p.add_argument('--performance-only',action='store_true')
    p.add_argument('--mouse',action='store_true')
    args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    output=args.output
    output.mkdir(parents=True,exist_ok=True)
    remote=f'cd {shlex.quote(require("TELEOP_REMOTE_REPO"))} && {shlex.quote(require("TELEOP_BASE_PYTHON"))} -m teleop.load_probe'
    def capture(side):
        (output/f'local_{side}.json').write_text(json.dumps(probe(),indent=2))
        data=subprocess.check_output(profile_command(remote),text=True)
        (output/f'gpu_{side}.json').write_text(data)
    capture('before')
    try:
        subprocess.run([sys.executable,'-m','teleop.measure','--url',browser_url(),
                        '--output',str(output),*(['--performance-only'] if args.performance_only else []),*(['--mouse'] if args.mouse else []),*(['--idle'] if args.idle else [])],check=True,cwd=root)
    finally:
        capture('after')


if __name__=='__main__':main()
