"""Real temporary listeners and conservative project tunnel identity checks."""
import os
import socket
import unittest
from teleop.site import ROOT,check_local_port,local_port_owners,is_project_tunnel

CFG={'TELEOP_REMOTE_PORT':'19001','TELEOP_SSH_USER':'tester','TELEOP_GPU_HOST':'100.1.2.3',
     'TELEOP_SSH_PORT':'2022','TELEOP_SSH_IDENTITY':'/tmp/project-test-key'}


class LocalPortTest(unittest.TestCase):
    def test_listener_details_and_no_kill_for_unrelated_process(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
            owners=local_port_owners(port)
            self.assertTrue(any(o['pid']==os.getpid() and o['command'] and o['started'] for o in owners))
            with self.assertRaisesRegex(ValueError,'default keeps'):check_local_port(port,CFG,emit=lambda _:None)
            with self.assertRaisesRegex(ValueError,'non-project tunnel'):check_local_port(port,CFG,True,emit=lambda _:None)
            self.assertTrue(local_port_owners(port))
        self.assertEqual(check_local_port(port,CFG,emit=lambda _:None),[])

    def test_tunnel_requires_exact_endpoint_and_project_evidence(self):
        owner={'exe':'/usr/bin/ssh','uid':os.getuid(),'cwd':'/tmp','markers':{'TELEOP_TUNNEL_PROJECT':str(ROOT.resolve())},
               'argv':['ssh','-T','-p','2022','-i',CFG['TELEOP_SSH_IDENTITY'],'-L','0.0.0.0:12345:127.0.0.1:19001','tester@100.1.2.3','cat >/dev/null']}
        self.assertTrue(is_project_tunnel(owner,12345,CFG))
        self.assertFalse(is_project_tunnel(owner,12346,CFG))
        self.assertFalse(is_project_tunnel(dict(owner,exe='/usr/bin/python'),12345,CFG))
        self.assertFalse(is_project_tunnel(dict(owner,markers={}),12345,CFG))
        self.assertFalse(is_project_tunnel(owner,12345,dict(CFG,TELEOP_GPU_HOST='other-host')))


class PortReuseTest(unittest.TestCase):
    def test_prechecks_accept_time_wait_but_reject_a_real_listener(self):
        from pathlib import Path
        import time
        from xbox_gamepad_physics.teleop.remote import _available
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0)); listener.listen()
        port = listener.getsockname()[1]
        client = socket.create_connection(('127.0.0.1', port))
        accepted, _ = listener.accept()
        try:
            with self.assertRaises(OSError):
                _available(port)
            with self.assertRaises(ValueError):
                check_local_port(port, {}, emit=lambda _: None)
            # The server actively closes; after the peer FIN its port is TIME_WAIT.
            accepted.close()
            self.assertEqual(client.recv(1), b'')
            client.close(); listener.close()
            deadline = time.monotonic() + 1
            while True:
                states = [row.split()[3] for row in Path('/proc/net/tcp').read_text().splitlines()[1:]
                          if int(row.split()[1].split(':')[1], 16) == port]
                if '06' in states or time.monotonic() >= deadline:
                    break
                time.sleep(.01)
            self.assertIn('06', states, 'the experiment must actually establish TIME_WAIT')
            _available(port)
            self.assertEqual(check_local_port(port, {}, emit=lambda _: None), [])
        finally:
            accepted.close(); client.close(); listener.close()
