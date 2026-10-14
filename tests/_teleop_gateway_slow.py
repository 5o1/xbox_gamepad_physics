"""Real local gateway + TCP clients; CPU H.264 fixture replaces only the workers/encoder."""
import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import aiohttp
from xbox_gamepad_physics.teleop.stream.gateway import client_operation
from xbox_gamepad_physics.teleop.stream.ipc import unpack
from _teleop_gateway_client import GatewayProcess, OPENER


class ClientCancellationTest(unittest.IsolatedAsyncioTestCase):
    async def test_peer_cancel_is_local_but_gateway_cancel_propagates(self):
        async def peer_cancel():
            raise asyncio.CancelledError()
        with self.assertRaises(ConnectionError):
            await client_operation(peer_cancel(), .2)
        entered, finished = asyncio.Event(), asyncio.Event()
        async def blocked():
            entered.set()
            try:await asyncio.Event().wait()
            finally:finished.set()
        outer = asyncio.create_task(client_operation(blocked(), 10))
        await entered.wait();outer.cancel()
        with self.assertRaises(asyncio.CancelledError):await outer
        await asyncio.wait_for(finished.wait(), .5)

    async def test_timeout_bounds_a_blocked_close(self):
        async def blocked_close():await asyncio.Event().wait()
        started=time.monotonic()
        with self.assertRaises(asyncio.TimeoutError):await client_operation(blocked_close(), .02)
        self.assertLess(time.monotonic()-started, .5)


def stalled_socket(port):
    sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024)
    sock.settimeout(3);sock.connect(('127.0.0.1',port))
    sock.sendall((f'GET /video HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n'
                  'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                  'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
    header=b''
    while not header.endswith(b'\r\n\r\n'):header+=sock.recv(1)
    assert b'101 Switching Protocols' in header,header
    return sock  # Deliberately never read any frame.


class RealGatewaySlowClientTest(unittest.TestCase):
    def test_slow_A_keeps_B_alive_reconnect_decodes_and_shutdown_exits(self):
        with tempfile.TemporaryDirectory(prefix='xgp-ws-') as folder:
            root=Path(folder);source=root/'source.h264'
            subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-threads','1','-filter_threads','1',
                            '-f','lavfi','-i','testsrc=size=64x64:rate=30','-frames:v','30','-pix_fmt','yuv420p',
                            '-c:v','libx264','-preset','ultrafast','-g','5','-bf','0','-x264-params','aud=1:repeat-headers=1',
                            '-f','h264',str(source)],check=True,capture_output=True)
            gateway=GatewayProcess(sys.executable,root,source=source)
            stalled=None
            try:
                gateway.ready();stalled=stalled_socket(gateway.port)
                async def receive():
                    async with aiohttp.ClientSession(trust_env=False) as client:
                        async with client.ws_connect(gateway.url+'/video') as healthy:
                            first=None;count=0;end=time.monotonic()+8
                            while time.monotonic()<end:
                                frame=await healthy.receive(timeout=2)
                                self.assertEqual(frame.type,aiohttp.WSMsgType.BINARY)
                                meta,_=unpack(frame.data);count+=1
                                if first is None:first=meta['frame_id']
                                if 'kind=video reason=' in (root/'stdout.log').read_text() and count>=12:break
                            else:self.fail('the real stalled TCP client was not disconnected')
                            self.assertGreater(meta['frame_id'],first)
                            self.assertIsNone(gateway.process.poll())
                            async with client.get(gateway.url+'/health') as response:
                                self.assertEqual(response.status,200);self.assertTrue((await response.json())['ready'])
                            stalled.close()
                            # A new decoder gets the next IDR, while B stays connected.
                            async with client.ws_connect(gateway.url+'/video') as reconnected:
                                units=[]
                                for index in range(6):
                                    frame=await reconnected.receive(timeout=2)
                                    self.assertEqual(frame.type,aiohttp.WSMsgType.BINARY)
                                    meta,unit=unpack(frame.data);units.append(unit)
                                    if index==0:self.assertTrue(meta['key'] and meta['codec'])
                                reconnect=root/'reconnect.h264';reconnect.write_bytes(b''.join(units))
                                decoded=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-threads','1',
                                                        '-i',str(reconnect),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
                                                       check=True,capture_output=True).stdout
                                self.assertEqual(len(decoded),64*64*3)
                                self.assertGreater(max(decoded)-min(decoded),20)
                            frame=await healthy.receive(timeout=2)
                            self.assertEqual(frame.type,aiohttp.WSMsgType.BINARY)
                            # Control responses also use the isolated operation path.
                            async with client.ws_connect(gateway.url+'/control') as control:
                                self.assertEqual((await control.receive_json())['kind'],'welcome')
                                await control.send_json({'kind':'probe-clock','id':7})
                                self.assertEqual((await control.receive_json())['id'],7)
                asyncio.run(receive())
                self.assertEqual(gateway.shutdown()[0],200)
                self.assertEqual(gateway.exited(timeout=10),0)
                self.assertNotIn('Error handling request',gateway.stderr())
            finally:
                if stalled:stalled.close()
                gateway.close()


if __name__=='__main__':unittest.main(verbosity=2)
