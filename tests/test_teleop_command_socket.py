"""Real IPC with paths longer than sockaddr_un; no SAPIEN dependency."""
from pathlib import Path
import socket
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from teleop.stream.commands import command_address


class CommandSocketTest(unittest.TestCase):
    def test_long_run_paths_and_distinct_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/('r'*100);root.mkdir()
            a=root/'live-20261012-025905';b=root/'live-20261012-025917';a.mkdir();b.mkdir()
            self.assertGreaterEqual(len(str(a/'commands.sock').encode()),108)
            first=command_address(a);second=command_address(b)
            self.assertNotEqual(first,second)
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sender:
                receiver.bind(first);receiver.settimeout(1)
                sender.sendto(b'command',command_address(a))
                self.assertEqual(receiver.recv(100),b'command')
            # No lingering endpoint: binding the same address after close works.
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as receiver:receiver.bind(first)


if __name__=='__main__':unittest.main()
