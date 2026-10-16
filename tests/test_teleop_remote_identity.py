"""Checked remote cleanup must never signal a reused/unrelated process identity."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
import os
import threading
from unittest import mock
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from xbox_gamepad_physics.teleop import remote_session
from xbox_gamepad_physics.teleop.remote_session import cleanup,record_processes,RECEIPT


class RemoteIdentityTest(unittest.TestCase):
    def test_changed_creation_time_is_not_signalled(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)
            child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
            try:
                data=record_processes(run,0,[child.pid]);data['processes'][0]['start_ticks']+=1
                (run/RECEIPT).write_text(json.dumps(data))
                result=cleanup(run,wait=0)
                self.assertEqual(result['identity_changed_not_signalled'],[child.pid])
                self.assertEqual(result['forced_cleanup'],[])
                self.assertIsNone(child.poll())
            finally:child.terminate();child.wait(timeout=5)
    def test_owned_process_cleanup_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder);child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
            try:
                record_processes(run,0,[child.pid]);result=cleanup(run,wait=0)
                self.assertTrue(result['all_exited'])
                self.assertEqual(result['forced_cleanup'],[{'pid':child.pid,'signal':'SIGTERM'}])
                child.wait(timeout=5)
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=5)

    def test_non200_shutdown_is_reported_and_only_owned_process_is_cleaned(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):self.send_response(500);self.end_headers()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder);child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
            try:
                record_processes(run,server.server_port,[child.pid])
                python=os.environ.get('XBOX_TELEOP_TEST_PYTHON',sys.executable)
                result=subprocess.run([python,'-m','xbox_gamepad_physics.teleop.remote_session','cleanup',
                    '--run',str(run),'--shutdown','--wait','0'],capture_output=True,text=True)
                self.assertEqual(result.returncode,2,result.stderr)
                report=json.loads(result.stdout)
                self.assertEqual(report['shutdown']['status'],500)
                self.assertTrue(report['shutdown']['error']);self.assertTrue(report['all_exited'])
                self.assertEqual(report['forced_cleanup'],[{'pid':child.pid,'signal':'SIGTERM'}])
                child.wait(timeout=5)
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=5)
                server.shutdown();server.server_close();thread.join(timeout=2)

    def test_incomplete_stop_log_does_not_prevent_exit_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder);record_processes(run,0,[])
            (run/'stop_reason.json').write_text('{"run":')
            result=cleanup(run,wait=0)
            self.assertTrue(result['all_exited'])
            self.assertIsNone(result['stop_reason']);self.assertTrue(result['stop_reason_error'])

    def test_same_process_with_uncertain_argv_is_not_reported_exited(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder);child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
            try:
                data=record_processes(run,0,[child.pid]);data['processes'][0]['argv']='uncertain argv'
                (run/RECEIPT).write_text(json.dumps(data))
                result=cleanup(run,wait=0)
                self.assertFalse(result['all_exited'])
                self.assertEqual(result['remaining_pids'],[child.pid])
                self.assertEqual(result['forced_cleanup'],[])
                self.assertIsNone(child.poll())
            finally:child.terminate();child.wait(timeout=5)

    def test_transiently_empty_argv_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder);child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
            try:
                real=remote_session.identity;reads=[]
                def flaky(pid):
                    value=real(pid);reads.append(pid)
                    return {**value,'argv':''} if value and len(reads)<3 else value
                with mock.patch.object(remote_session,'identity',flaky):
                    data=record_processes(run,0,[child.pid])
                self.assertTrue(data['processes'][0]['argv'])
                result=cleanup(run,wait=0)
                self.assertTrue(result['all_exited'])
                self.assertEqual(result['forced_cleanup'],[{'pid':child.pid,'signal':'SIGTERM'}])
                child.wait(timeout=5)
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=5)
