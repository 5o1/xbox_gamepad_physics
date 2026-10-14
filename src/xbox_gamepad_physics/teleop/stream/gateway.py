"""Separate NVENC/HTTP/WS process; physics never waits for a consumer."""
import argparse
import asyncio
from collections import deque
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import time

from aiohttp import web

from .commands import command_address
from .h264 import AccessUnits, info
from .ipc import Latest, SNAPSHOT_CAPACITY, FRAME_CAPACITY, packet, unpack

from ..site import validate_tunnel_timeout,tunnel_timeout_argument,IdleWatchdog
from ..record import DEFAULT_FORMAT,open_writer,record_path,write_row
PACKAGE = Path(__file__).resolve().parents[1]
from xbox_gamepad_physics.web.server import UI_ROOT
from xbox_gamepad_physics.gpu import gpu_environment


async def client_operation(operation, timeout):
    """Bound one peer's IO, preserving cancellation of the gateway task itself.

    asyncio.wait reports cancellation of its child as a completed task, while
    cancellation of this caller raises directly. This works on Python 3.10
    without conflating a peer's cancelled drain waiter with gateway shutdown.
    """
    task = asyncio.create_task(operation)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            raise asyncio.TimeoutError('client IO deadline')
        if task.cancelled():
            raise ConnectionError('client IO cancelled')
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        # Retrieve late errors without waiting indefinitely for a broken peer.
        task.add_done_callback(lambda result: None if result.cancelled() else result.exception())


async def serve(args):
    """Run workers on --gpu in the caller's visible list; all children see GPU 0."""
    env = gpu_environment(args.gpu)
    timeout_value=getattr(args,'tunnel_timeout_s',None)
    timeout=validate_tunnel_timeout(60 if timeout_value is None else timeout_value)
    watchdog=IdleWatchdog(timeout)
    children, logs, tasks = [], [], []
    monitor = runner = snapshot = frames = sock = metrics = ffmpeg = bound = None
    try:
        bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bound.bind(("127.0.0.1", args.port))
        bound.listen(128)
        bound.setblocking(False)
        args.run.mkdir(parents=True, exist_ok=False)
        if getattr(args,"log_to_file",False):
            with (args.run/"gateway.log").open("a",buffering=1) as output:
                os.dup2(output.fileno(),1)
                os.dup2(output.fileno(),2)
        def publish_processes():
            if getattr(args,"log_to_file",False):
                from ..remote_session import record_processes
                record_processes(args.run,bound.getsockname()[1],
                    [os.getpid(),*[c.pid for c in children],*([ffmpeg.pid] if ffmpeg else [])])
        publish_processes()
        endpoint = command_address(args.run)
        snapshot = Latest(args.run/"snapshot.mmap", SNAPSHOT_CAPACITY, True)
        frames = Latest(args.run/"frame.mmap", FRAME_CAPACITY, True)
        source = PACKAGE.parent.parent
        if source.name == "src" and (source.parent / "pyproject.toml").is_file():
            env["PYTHONPATH"] = str(source)
        if getattr(args, "resources", None):
            env["XBOX_GAMEPAD_PHYSICS_RESOURCES"] = str(args.resources)
        stopped=asyncio.Event()
        def request_stop(reason):
            stopped.set()
            now=time.monotonic()
            detail={'run':args.run.name,'reason':reason,'timeout_s':timeout,
                    'started_monotonic_s':watchdog.started,'last_activity_monotonic_s':watchdog.last_activity,
                    'last_activity_kind':watchdog.last_kind,'stopped_monotonic_s':now,
                    'idle_seconds':now-watchdog.last_activity,'gateway_pid':os.getpid(),
                    'child_pids':[child.pid for child in children]}
            try:(args.run/'stop_reason.json').write_text(json.dumps(detail,indent=2)+'\n')
            except OSError:pass
            try:os.write(1,('teleop stop '+json.dumps(detail)+'\n').encode('utf-8'))
            except OSError:pass
        async def idle_monitor():
            while not stopped.is_set():
                if watchdog.expired():
                    request_stop('control-idle-timeout')
                    for child in children:
                        if child.poll() is None:child.terminate()
                    return
                await asyncio.sleep(.1)
        monitor=asyncio.create_task(idle_monitor())
        loop=asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM,lambda:request_stop('sigterm'))
        loop.add_signal_handler(signal.SIGINT,lambda:request_stop('sigint'))
        def spawn(module, extra, log, python=None):
            stream = (args.run/log).open("w")
            logs.append(stream)
            child = subprocess.Popen([python or args.simulation_python or sys.executable,"-u","-m",module,"--run",str(args.run),*extra],cwd=args.run,env=env,
                                     stdout=stream,stderr=subprocess.STDOUT)
            children.append(child)
            publish_processes()
            return child
        def worker_failure(child, name):
            path=args.run/name
            tail=path.read_text(errors="replace")[-12000:] if path.exists() else "(log not created)"
            return RuntimeError(f"worker pid={child.pid} exited with status {child.returncode}; {path}\n{tail or '(empty child log)'}")

        record_format=getattr(args,'record_format',None)
        physics = spawn("xbox_gamepad_physics.teleop.server", ["--config",str(args.config),
                                          *(["--robotwin-root",str(args.robotwin_root)] if getattr(args,"robotwin_root",None) else []),*(["--record-format",record_format] if record_format else []),*(["--steps",str(args.steps)] if args.steps else []),
                                          *(["--commands",str(args.commands)] if args.commands else []),
                                          *(["--ball-case",args.ball_case] if args.ball_case else []),
                                          *(["--ball-radius-m",str(args.ball_radius_m)] if args.ball_radius_m is not None else []),
                                          *(["--ball-plan",str(args.ball_plan)] if args.ball_plan else []),
                                          "--collision",args.collision],"physics.log",args.physics_python)
        if record_format is None:
            # The gateway environment intentionally has no YAML dependency. Read
            # the physics owner's existing atomic completed-state publication.
            while not (published := snapshot.read()):
                if stopped.is_set():break
                if physics.poll() is not None:raise worker_failure(physics,'physics.log')
                await asyncio.sleep(.01)
            record_format=json.loads(published[1])['config'].get('stream',{}).get('record_format',DEFAULT_FORMAT) if published else DEFAULT_FORMAT
        renderer = None if args.stream_off or stopped.is_set() else spawn("xbox_gamepad_physics.teleop.render", ["--candidate", args.render_candidate], "renderer.log")
        print(f"teleop run={args.run} physics_pid={physics.pid} renderer_pid={renderer.pid if renderer else None}",flush=True)
        clients = {}
        control_peers = set()
        peer_transports = {}

        async def disconnect(ws, reason):
            peer = peer_transports.pop(ws, None)
            clients.pop(ws, None)
            control_peers.discard(ws)
            if peer is None:
                return
            kind, transport = peer
            try:
                os.write(1, f'teleop client disconnected kind={kind} reason={reason}\n'.encode())
            except OSError:
                pass
            try:
                await client_operation(ws.close(drain=False), .25)
            except Exception:
                pass  # This peer is already removed; the transport is aborted below.
            finally:
                if transport is not None:
                    transport.abort()
        fifo = deque()
        sock = socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        codec = None
        last_seq = 0
        metrics = open_writer(record_path(args.run,'stream_timing',record_format),record_format)
        ffmpeg = None
        if not args.stream_off and not stopped.is_set():
            encoder_log = (args.run/"encoder.log").open("w")
            logs.append(encoder_log)
            ffmpeg = await asyncio.create_subprocess_exec(
                "ffmpeg","-hide_banner","-loglevel","warning","-threads","2","-filter_threads","2",
                "-f","rawvideo","-pixel_format","rgb24","-video_size","1280x720","-framerate","60","-i","pipe:0",
                "-an","-c:v","h264_nvenc","-preset","p1","-tune","ull","-profile:v","main","-level:v","4.2",
                "-gpu","0","-bf","0","-rc-lookahead","0","-zerolatency","1","-delay","0","-g","30","-b:v","6M",
                "-maxrate","6M","-bufsize","300k","-aud","1","-vsync","0","-flush_packets","1","-f","h264","pipe:1",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=encoder_log, env=env)
            publish_processes()

        def current():
            data = snapshot.read()
            return json.loads(data[1]) if data else None

        def forward(message):
            nonlocal last_seq
            last_seq = max(last_seq,message["seq"])
            message["received_ns"] = time.monotonic_ns()
            sock.sendto(json.dumps(message).encode(),endpoint)

        async def control(request):
            nonlocal last_seq
            ws = web.WebSocketResponse(heartbeat=10)
            await ws.prepare(request)
            control_peers.add(ws)
            peer_transports[ws] = ('control', request.transport)
            now = current()
            last_seq = max(last_seq,now.get("last_input_seq",0) if now else 0)
            try:
                await client_operation(ws.send_json({"kind":"welcome","seq_base":last_seq,"input_config":now["input_config"] if now else None}), .05)
                async for item in ws:
                    if item.type == web.WSMsgType.TEXT:
                        received_ns = time.monotonic_ns()
                        message = json.loads(item.data)
                        watchdog.activity()
                        if message.get("kind") == "probe-clock":
                            # Measurement only: do not renew the control lease or consume a seq.
                            await client_operation(ws.send_json({"kind":"probe-clock", "id":message["id"],
                                                "server_received_ns":received_ns,
                                                "server_sent_ns":time.monotonic_ns()}), .05)
                        elif message.get("kind") == "heartbeat":
                            forward({"kind":"heartbeat", "seq":last_seq})
                        elif message.get("kind") == "ping":
                            forward({"kind":"heartbeat", "seq":last_seq})
                            await client_operation(ws.send_json({"kind":"pong","id":message["id"]}), .05)
                        else:
                            forward(message)
            except Exception as error:
                await disconnect(ws, type(error).__name__)
            finally:
                await disconnect(ws, 'control-eof')
                if not stopped.is_set():watchdog.activity('control-disconnect')
                last_seq += 1
                if physics.poll() is None:
                    forward({"kind":"disconnect","seq":last_seq})
            return ws

        async def video(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            peer_transports[ws] = ('video', request.transport)
            # A new/reconnected decoder must receive SPS/PPS + IDR first.
            # NVENC's existing GOP is 30 frames; no delta frame is sent before it.
            clients[ws] = True
            try:
                async for _ in ws:
                    pass
            except Exception as error:
                await disconnect(ws, type(error).__name__)
            finally:
                await disconnect(ws, 'video-eof')
            return ws

        def health_payload():
            now = current()
            rendered = args.stream_off or bool(frames.read()) and codec is not None
            return {"run":args.run.name,"ready":not stopped.is_set() and bool(now) and rendered and physics.poll() is None
                        and (renderer is None or renderer.poll() is None),
                    "tunnel_timeout_s":timeout,"gateway_pid":os.getpid(),
                    "child_pids":[c.pid for c in children],"physics_alive":physics.poll() is None,
                    "renderer_alive":renderer.poll() is None if renderer else None,
                    "encoder_pid":ffmpeg.pid if ffmpeg else None}

        async def health(request):
            return web.json_response(health_payload())

        async def raw_writer():
            generation = 0
            while physics.poll() is None:
                value = frames.read()
                if value and value[0] != generation:
                    generation = value[0]
                    metadata, rgb = unpack(value[1])
                    metadata["encoder_input_ns"] = time.monotonic_ns()
                    fifo.append(metadata)
                    ffmpeg.stdin.write(rgb)
                    await ffmpeg.stdin.drain()
                else:
                    await asyncio.sleep(.001)

        async def encoded_reader():
            nonlocal codec
            parser = AccessUnits()
            while data := await ffmpeg.stdout.read(65536):
                for unit in parser.feed(data):
                    metadata = fifo.popleft()
                    key, new_codec = info(unit)
                    codec = new_codec or codec
                    end = time.monotonic_ns()
                    metadata.update({"key":key,"codec":codec,"encode_ns":end-metadata["encoder_input_ns"],
                                     "encoded_ns":end,"bytes":len(unit)})
                    message = packet(metadata,unit)
                    send_start = time.monotonic_ns()
                    for ws in list(clients):
                        if clients.get(ws) and not key:
                            continue
                        clients[ws] = False
                        try:
                            await client_operation(ws.send_bytes(message), .05)
                        except Exception as error:
                            await disconnect(ws, type(error).__name__)
                    write_row(metrics,{"frame_id":metadata["frame_id"],"step":metadata["step"],
                                              "encode_ns":metadata["encode_ns"],"send_ns":time.monotonic_ns()-send_start,
                                              "bytes":len(message),"clients":len(clients)})

        app = web.Application()
        async def shutdown(request):
            if request.query.get("run") != args.run.name:
                raise web.HTTPConflict(text="different run")
            request_stop('shutdown-request')
            return web.json_response({"stopping":True})
        async def favicon(request):
            return web.Response(status=204)
        app.router.add_get("/favicon.ico",favicon)
        app.router.add_post("/shutdown",shutdown)
        app.router.add_get("/control",control)
        app.router.add_get("/video",video)
        app.router.add_get("/health",health)
        if args.ball_case:
            async def probe_request(request):
                message=await request.json()
                # This moves only the test sphere; it never supplies a signal frame.
                forward({"kind":"probe","action":message["action"],"seq":last_seq})
                return web.json_response({"accepted":True})
            app.router.add_post("/probe",probe_request)
        app.router.add_get("/",lambda request:web.FileResponse(PACKAGE/"web/index.html"))
        app.router.add_static("/web/",PACKAGE/"web")
        app.router.add_static("/viewer/gamepad_overlay/",UI_ROOT/"gamepad_overlay")
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner,bound).start()
        announced = False
        tasks = [] if args.stream_off or stopped.is_set() else [asyncio.create_task(raw_writer()),asyncio.create_task(encoded_reader())]
        while physics.poll() is None and not stopped.is_set():
            if renderer is not None and renderer.poll() is not None:
                raise worker_failure(renderer,"renderer.log")
            for task in tasks:
                if task.done():
                    task.result()
                    raise RuntimeError("encoder task exited; see encoder.log")
            if not announced and health_payload()["ready"]:
                url=f"http://127.0.0.1:{bound.getsockname()[1]}/"
                print(f"Teleop ready {url}",flush=True)
                announced=True
                if getattr(args,"open_browser",False):
                    import webbrowser
                    webbrowser.open(url)
            await asyncio.sleep(.2)
        if not stopped.is_set() and physics.poll() is not None:
            if args.steps is None or physics.returncode != 0:
                raise worker_failure(physics,"physics.log")
    finally:
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor,return_exceptions=True)
        if 'peer_transports' in locals():
            await asyncio.gather(*(disconnect(ws, 'gateway-stop') for ws in list(peer_transports)))
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        for child in children:
            if child.poll() is None:child.terminate()
        for child in children:
            try:child.wait(timeout=35)
            except subprocess.TimeoutExpired:
                child.kill();child.wait(timeout=5)
        if ffmpeg is not None and ffmpeg.returncode is None:
            ffmpeg.stdin.close()
            try:await asyncio.wait_for(ffmpeg.wait(),5)
            except asyncio.TimeoutError:
                ffmpeg.kill();await ffmpeg.wait()
        if runner is not None:await runner.cleanup()
        for item in (snapshot, frames, sock, metrics, bound):
            if item is not None:item.close()
        for log in logs:log.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--config",type=Path,default=PACKAGE/"templates/teleop_gripper.yaml")
    parser.add_argument("--port",type=int,default=8775)
    parser.add_argument("--gpu",type=int,default=0)
    parser.add_argument("--robotwin-root",type=Path)
    parser.add_argument("--resources",type=Path)
    parser.add_argument("--open-browser",action="store_true")
    parser.add_argument("--log-to-file",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--steps",type=int)
    parser.add_argument("--commands",type=Path)
    parser.add_argument("--record-format",choices=['binary','jsonl'],help='override stream.record_format')
    parser.add_argument('--tunnel-timeout-s',type=tunnel_timeout_argument,default=60)
    parser.add_argument("--stream-off",action="store_true")
    from ..ball_probe import CASES
    parser.add_argument("--ball-case",choices=CASES)
    parser.add_argument("--ball-radius-m",type=float)
    parser.add_argument("--ball-plan",type=Path)
    parser.add_argument("--physics-python")
    parser.add_argument("--simulation-python", help="override both physics and renderer environment")
    parser.add_argument("--collision",choices=["coacd","sdf"],default="sdf")
    parser.add_argument("--render-candidate",choices=("raster","rt"),default="rt")
    asyncio.run(serve(parser.parse_args()))


if __name__ == "__main__":
    main()
