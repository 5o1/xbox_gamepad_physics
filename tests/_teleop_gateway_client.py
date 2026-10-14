"""Local-process harness: real HTTP and signals, only the physics owner is a fixture."""
from pathlib import Path
import json
import os
import select
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request

HELPER=Path(__file__).with_name('_teleop_gateway_process.py')
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}))


class GatewayProcess:
    def __init__(self, python, root, *, pipe=False, timeout=60, deny_stop_file=False, source=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.run=self.root/'run';self.pipe=pipe
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.url=f'http://127.0.0.1:{self.port}'
        self.output=(self.root/'stdout.log').open('w')
        self.errors=(self.root/'stderr.log').open('w')
        env=dict(os.environ);env.pop('PYTHONPATH',None)
        command=[python,str(HELPER),'gateway','--run',str(self.run),'--port',str(self.port),'--timeout',str(timeout)]
        if deny_stop_file:command.append('--deny-stop-file')
        if source:command+=['--source',str(source)]
        self.process=subprocess.Popen(command,cwd=self.root,env=env,
            stdout=subprocess.PIPE if pipe else self.output,stderr=self.errors,bufsize=0)
        self.health=None;self.ready_lines=[]
    def ready(self):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if self.process.poll() is not None:raise RuntimeError(self.stderr())
            try:
                with OPENER.open(self.url+'/health',timeout=.2) as response:self.health=json.load(response)
                if self.health['ready']:break
            except OSError:pass
            time.sleep(.02)
        else:raise TimeoutError('gateway health not ready')
        if self.pipe:
            # Read both startup lines before closing the only read end.
            while not any(b'Teleop ready ' in line for line in self.ready_lines):
                if not select.select([self.process.stdout],[],[],5)[0]:raise TimeoutError('missing ready log')
                self.ready_lines.append(self.process.stdout.readline())
        else:
            while 'Teleop ready ' not in (self.root/'stdout.log').read_text():
                if time.monotonic()>deadline:raise TimeoutError('missing ready log')
                time.sleep(.02)
        return self.health
    def break_stdout(self):
        assert self.pipe
        self.process.stdout.close()
    def shutdown(self):
        request=urllib.request.Request(self.url+'/shutdown?run='+self.run.name,method='POST')
        try:response=OPENER.open(request,timeout=3)
        except urllib.error.HTTPError as error:response=error
        with response:return response.status,response.read().decode()
    def stderr(self):return (self.root/'stderr.log').read_text(errors='replace')
    def exited(self, timeout=5):
        result=self.process.wait(timeout=timeout)
        for pid in self.health['child_pids']:
            try:os.kill(pid,0)
            except ProcessLookupError:continue
            raise AssertionError('fixture child remains alive')
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            sock.bind(('127.0.0.1',self.port))
        return result
    def close(self):
        # Failure cleanup is restricted to the child IDs returned by our process.
        if self.process.poll() is None:
            self.process.kill();self.process.wait(timeout=5)
        if self.health:
            for pid in self.health['child_pids']:
                try:os.kill(pid,signal.SIGTERM)
                except ProcessLookupError:pass
        if self.process.stdout and not self.process.stdout.closed:self.process.stdout.close()
        self.output.close();self.errors.close()
