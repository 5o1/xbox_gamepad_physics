"""Public local launch and explicit optional SSH transport."""
from pathlib import Path
import argparse
import asyncio
import os
import subprocess
import sys

TEMPLATES = Path(__file__).with_name('templates')


def add_arguments(parser):
    parser.add_argument('--mode',choices=('local','remote'),default='local')
    parser.add_argument('--robotwin-root',type=Path)
    parser.add_argument('--resources',type=Path)
    parser.add_argument('--output',type=Path,help='new session directory; must not exist')
    parser.add_argument('--gpu',type=int,help='Index into caller-visible CUDA_VISIBLE_DEVICES; physical device index when no mask is set')
    parser.add_argument('--port',type=int,default=None,help='GPU loopback HTTP port, default 8775')
    parser.add_argument('--config',type=Path)
    parser.add_argument('--open-browser',action='store_true')
    parser.add_argument('--log-to-file',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--stream-python',help='optional gateway interpreter; default current Python')
    parser.add_argument('--simulation-python',help='optional physics/render interpreter; default current Python')
    parser.add_argument('--render-candidate','--render',choices=('raster','rt'),default='rt')
    parser.add_argument('--collision',choices=('sdf','coacd'),default='sdf')
    parser.add_argument('--sapien',choices=('3.0.3',),default='3.0.3')
    parser.add_argument('--tunnel-timeout-s',type=int,default=None)
    remote=parser.add_argument_group('optional remote transport (never used by local)')
    remote.add_argument('--site',type=Path,help='explicit private KEY=value site file')
    remote.add_argument('--ssh',help='user OpenSSH alias or user@host')
    remote.add_argument('--identity',type=Path)
    remote.add_argument('--ssh-port',type=int)
    remote.add_argument('--remote-python',help='remote interpreter containing the same wheel')
    remote.add_argument('--local-port',type=int)
    remote.add_argument('--windows-relay',action='store_true')
    remote.add_argument('--skip-windows-relay',action='store_true',help='Validation only: skip the Windows relay and access health via WSL loopback')
    remote.add_argument('--wsl-interface')
    remote.add_argument('--relay-port',type=int)
    remote.add_argument('--local-output',type=Path,help='remote client logs and temporary FIFO')
    remote.add_argument('--stop-existing',action='store_true',help='remote: stop only an identified old session/tunnel')
    parser.set_defaults(handler=command)


def command(args):
    try:
        if args.mode=='remote':
            from .remote import run
            return run(args)
        if args.site or args.ssh or args.windows_relay or args.skip_windows_relay or args.stop_existing:
            raise ValueError('SSH, site configuration, relay, and --stop-existing require --mode remote')
        for name in ('robotwin_root','resources','output','gpu'):
            if getattr(args,name) is None:raise ValueError('local requires an explicit --'+name.replace('_','-'))
        if args.stream_python and Path(args.stream_python).resolve()!=Path(sys.executable).resolve():
            # Select an already installed interpreter, without mutating environments.
            argv=sys.argv[1:]
            argv=list(argv)
            if '--stream-python' in argv:
                i=argv.index('--stream-python');del argv[i:i+2]
            else:argv=[v for v in argv if not v.startswith('--stream-python=')]
            if not args.simulation_python:argv+=['--simulation-python',sys.executable]
            os.execv(args.stream_python,[args.stream_python,'-m','xbox_gamepad_physics',*argv])
        from .site import validate_tunnel_timeout
        from .stream.gateway import serve
        args.run=args.output.expanduser().resolve()
        args.resources=args.resources.expanduser().resolve()
        args.robotwin_root=args.robotwin_root.expanduser().resolve(strict=True)
        args.config=(args.config or TEMPLATES/'teleop_gripper.yaml').expanduser().resolve(strict=True)
        args.port=8775 if args.port is None else args.port
        args.tunnel_timeout_s=validate_tunnel_timeout(60 if args.tunnel_timeout_s is None else args.tunnel_timeout_s)
        args.simulation_python=args.simulation_python or sys.executable
        # The same installed implementation serves live, scripted and legacy entry points.
        for name,value in dict(physics_python=None,steps=None,commands=None,record_format=None,
                               stream_off=False,ball_case=None,ball_radius_m=None,ball_plan=None).items():
            setattr(args,name,value)
        asyncio.run(serve(args))
        return 0
    except (OSError,ValueError,RuntimeError,ImportError,subprocess.SubprocessError) as error:
        print(f'teleop: {error}',file=sys.stderr)
        return 2


def add_replay_arguments(parser):
    parser.add_argument('record',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resources',type=Path,required=True)
    parser.add_argument('--robotwin-root',type=Path)
    parser.add_argument('--steps',type=int,help='replay a prefix, preserving all step commands')
    parser.set_defaults(handler=replay_command)


def replay_command(args):
    from .replay import replay
    if args.steps is not None and args.steps<1:raise ValueError('--steps must be positive')
    os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(args.resources.expanduser().resolve())
    result=replay(args.record.resolve(),args.output.resolve(),steps=args.steps,
                  robotwin_root=args.robotwin_root.resolve() if args.robotwin_root else None)
    import json
    print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1
