"""Before/after measurement load evidence; never run inside the FPS window."""
import json
from pathlib import Path
import socket
import subprocess
import time


def cpu_ticks():
    return [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]


def probe():
    before=cpu_ticks();start=time.monotonic();time.sleep(.5);after=cpu_ticks()
    delta=[b-a for a,b in zip(before,after)];total=sum(delta[:8]);idle=delta[3]+delta[4]
    gpu=subprocess.run(['nvidia-smi'],capture_output=True,text=True) if subprocess.run(['which','nvidia-smi'],capture_output=True).returncode==0 else None
    processes=subprocess.check_output(['ps','-eo','pid,ppid,pcpu,pmem,etime,args','--sort=-pcpu'],text=True)
    return {'host':socket.gethostname(),'wall_time_ns':time.time_ns(),'sample_seconds':time.monotonic()-start,
            'cpu_busy_percent':100*(total-idle)/total,'loadavg':Path('/proc/loadavg').read_text().strip(),
            'nvidia_smi':gpu.stdout if gpu else None,'processes':processes}


if __name__=='__main__':
    print(json.dumps(probe(),indent=2))
