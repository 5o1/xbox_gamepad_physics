"""Actual gateway HTTP/signals with a CPU fixture; no SAPIEN, GPU or FFmpeg."""
from pathlib import Path
import importlib.util
import os
import signal
import json
import socket
import subprocess
import time
import sys
import tempfile
import unittest
from _teleop_gateway_client import GatewayProcess,HELPER,OPENER

PYTHON=os.environ.get('XBOX_TELEOP_TEST_PYTHON',sys.executable)


@unittest.skipUnless(os.environ.get('XBOX_TELEOP_TEST_PYTHON') or importlib.util.find_spec('aiohttp'),
                     'gateway process tests need aiohttp or XBOX_TELEOP_TEST_PYTHON')
class GatewayShutdownTest(unittest.TestCase):
    def check_exit(self, action, *, deny_stop_file=False):
        with tempfile.TemporaryDirectory() as folder:
            proc=GatewayProcess(PYTHON,folder,pipe=True,timeout=10,deny_stop_file=deny_stop_file)
            try:
                proc.ready();proc.break_stdout()
                if action=='shutdown':self.assertEqual(proc.shutdown()[0],200)
                elif action=='term':proc.process.send_signal(signal.SIGTERM)
                elif action=='int':proc.process.send_signal(signal.SIGINT)
                self.assertEqual(proc.exited(timeout=15),0)
                if not deny_stop_file:self.assertTrue((proc.run/'stop_reason.json').is_file())
                self.assertNotIn('BrokenPipeError',proc.stderr())
            finally:proc.close()
    def test_shutdown_with_broken_stdout(self):self.check_exit('shutdown')
    def test_stop_reason_and_stdout_errors_do_not_block_shutdown(self):self.check_exit('shutdown',deny_stop_file=True)
    def test_idle_watchdog_exits_with_broken_stdout(self):self.check_exit('idle')
    def test_sigterm_exits_with_broken_stdout(self):self.check_exit('term')
    def test_sigint_exits_with_broken_stdout(self):self.check_exit('int')

    def test_detached_gateway_logs_to_file_and_checked_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'remote'
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            command=[PYTHON,'-m','xbox_gamepad_physics.teleop.remote_session','start','--run',str(run),'--',
                     PYTHON,str(HELPER),'gateway','--run',str(run),'--port',str(port),'--log-to-file']
            result=subprocess.run(command,capture_output=True,text=True,check=True)
            started=json.loads(result.stdout);pid=started['gateway_pid']
            try:
                deadline=time.monotonic()+10
                while True:
                    try:
                        with OPENER.open(f'http://127.0.0.1:{port}/health',timeout=.2) as response:state=json.load(response)
                        if state['ready']:break
                    except OSError:pass
                    if time.monotonic()>deadline:self.fail('detached session not ready')
                    time.sleep(.02)
                self.assertEqual(os.getpgid(pid),pid)
                self.assertEqual(os.readlink(f'/proc/{pid}/fd/1'),str(run/'gateway.log'))
                result=subprocess.run([PYTHON,'-m','xbox_gamepad_physics.teleop.remote_session','cleanup',
                    '--run',str(run),'--shutdown','--wait','3'],capture_output=True,text=True,check=True)
                clean=json.loads(result.stdout)
                self.assertEqual(clean['shutdown']['status'],200)
                self.assertTrue(clean['all_exited']);self.assertEqual(clean['forced_cleanup'],[])
            finally:
                subprocess.run([PYTHON,'-m','xbox_gamepad_physics.teleop.remote_session','cleanup',
                    '--run',str(run),'--wait','0'],capture_output=True,check=False)
