"""CPU-only physics boundary fixture for the actual gateway process."""
from pathlib import Path
import argparse
import asyncio
import json
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace


def physics(run):
    from xbox_gamepad_physics.teleop.stream.ipc import Latest, SNAPSHOT_CAPACITY
    stop = False
    def shutdown(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    from xbox_gamepad_physics.teleop.stream.commands import command_address
    commands = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    commands.bind(command_address(run));commands.settimeout(.02)
    latest = Latest(run/'snapshot.mmap', SNAPSHOT_CAPACITY)
    latest.write(json.dumps({'step':0,'config':{'stream':{'record_format':'jsonl'}},
                             'input_config':{},'last_input_seq':0}).encode())
    try:
        while not stop:
            try:commands.recv(65536)
            except socket.timeout:pass
    finally:
        latest.close();commands.close()


def gateway(args):
    from xbox_gamepad_physics.teleop.stream import gateway as module
    real_spawn = subprocess.Popen
    def fixture_spawn(command, **kwargs):
        if len(command)>3 and command[3] in ('xbox_gamepad_physics.teleop.server','xbox_gamepad_physics.teleop.render'):
            run = command[command.index('--run')+1]
            mode = 'physics' if command[3].endswith('.server') else 'renderer'
            return real_spawn([sys.executable,__file__,mode,'--run',run],**kwargs)
        assert list(command[1:3]) == [__file__,'encoder'], command
        return real_spawn(command,**kwargs)
    module.subprocess.Popen = fixture_spawn
    if args.source:
        real_async_spawn = asyncio.create_subprocess_exec
        async def encoder_spawn(*command, **kwargs):
            assert command[0] == 'ffmpeg', command
            return await real_async_spawn(sys.executable,__file__,'encoder','--run',str(args.run),
                                          '--source',str(args.source),**kwargs)
        module.asyncio.create_subprocess_exec = encoder_spawn
    if args.deny_stop_file:
        original = Path.write_text
        def write(path, *values, **kwargs):
            if path.name == 'stop_reason.json':raise PermissionError('test: stop log unavailable')
            return original(path,*values,**kwargs)
        Path.write_text = write
    values = SimpleNamespace(run=args.run,port=args.port,gpu=0,resources=None,
        robotwin_root=None,config=Path(__file__),simulation_python=sys.executable,
        physics_python=None,steps=None,commands=None,record_format='jsonl',
        stream_off=not bool(args.source),ball_case=None,ball_radius_m=None,ball_plan=None,
        collision='sdf',render_candidate='rt',tunnel_timeout_s=args.timeout,
        open_browser=False,log_to_file=args.log_to_file)
    asyncio.run(module.serve(values))


def renderer(run):
    from xbox_gamepad_physics.teleop.stream.ipc import Latest, FRAME_CAPACITY, packet
    stop = False
    def shutdown(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, shutdown)
    frames = Latest(run/'frame.mmap', FRAME_CAPACITY)
    try:
        frame = 0
        while not stop:
            frames.write(packet({'frame_id':frame,'step':frame,'last_input_seq':0},b'x'))
            frame += 1
            time.sleep(1/60)
    finally:frames.close()


def encoder(source):
    from xbox_gamepad_physics.teleop.stream.h264 import AccessUnits
    raw = source.read_bytes()
    units = AccessUnits().feed(raw+raw[:6])
    assert len(units) >= 10
    index = 0
    try:
        while sys.stdin.buffer.read(1):
            # A valid filler_data NAL makes actual TCP backpressure deterministic.
            filler = b'\x00\x00\x00\x01\x0c'+b'\xff'*(256*1024)+b'\x80'
            sys.stdout.buffer.write(units[index % len(units)]+filler)
            sys.stdout.buffer.flush()
            index += 1
    except BrokenPipeError:
        pass


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('physics','renderer','encoder','gateway'))
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--timeout',type=int,default=60)
    parser.add_argument('--deny-stop-file',action='store_true')
    parser.add_argument('--log-to-file',action='store_true')
    parser.add_argument('--source',type=Path)
    args=parser.parse_args()
    if args.mode=='physics':physics(args.run)
    elif args.mode=='renderer':renderer(args.run)
    elif args.mode=='encoder':encoder(args.source)
    else:gateway(args)
