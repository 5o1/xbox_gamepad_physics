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
import time

from aiohttp import web

from .commands import command_address
from .h264 import AccessUnits, info
from .ipc import Latest, SNAPSHOT_CAPACITY, FRAME_CAPACITY, packet, unpack

from ..site import require
ROOT = Path(__file__).resolve().parents[2]


async def serve(args):
    args.run.mkdir(parents=True, exist_ok=False)
    endpoint = command_address(args.run)
    snapshot = Latest(args.run/"snapshot.mmap", SNAPSHOT_CAPACITY, True)
    frames = Latest(args.run/"frame.mmap", FRAME_CAPACITY, True)
    env = dict(os.environ, PYTHONPATH=str(ROOT/"src")+os.pathsep+str(ROOT),CUDA_VISIBLE_DEVICES=str(args.gpu))
    children = []
    logs = []
    def spawn(module, extra, log, python=None):
        stream = (args.run/log).open("w")
        logs.append(stream)
        child = subprocess.Popen([python or args.simulation_python or require("TELEOP_BASE_PYTHON"),"-u","-m",module,"--run",str(args.run),*extra],cwd=ROOT,env=env,
                                 stdout=stream,stderr=subprocess.STDOUT)
        children.append(child)
        return child
    def worker_failure(child, name):
        path=args.run/name
        tail=path.read_text(errors="replace")[-12000:] if path.exists() else "(log not created)"
        return RuntimeError(f"worker pid={child.pid} exited with status {child.returncode}; {path}\n{tail or '(empty child log)'}")

    physics = spawn("teleop.server", ["--config",str(args.config),*(["--steps",str(args.steps)] if args.steps else []),
                                      *(["--commands",str(args.commands)] if args.commands else []),
                                      *(["--ball-case",args.ball_case] if args.ball_case else []),
                                      *(["--ball-radius-m",str(args.ball_radius_m)] if args.ball_radius_m is not None else []),
                                      *(["--ball-plan",str(args.ball_plan)] if args.ball_plan else []),
                                      "--collision",args.collision],"physics.log",args.physics_python)
    renderer = None if args.stream_off else spawn("teleop.render", ["--candidate", args.render_candidate], "renderer.log")
    print(f"teleop run={args.run} physics_pid={physics.pid} renderer_pid={renderer.pid if renderer else None}",flush=True)
    clients = {}
    control_peers = set()
    fifo = deque()
    sock = socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
    codec = None
    last_seq = 0
    metrics = (args.run/"stream_timing.jsonl").open("w")
    ffmpeg = None
    if not args.stream_off:
        ffmpeg = await asyncio.create_subprocess_exec(
            "ffmpeg","-hide_banner","-loglevel","warning","-threads","2","-filter_threads","2",
            "-f","rawvideo","-pixel_format","rgb24","-video_size","1280x720","-framerate","60","-i","pipe:0",
            "-an","-c:v","h264_nvenc","-preset","p1","-tune","ull","-profile:v","main","-level:v","4.2",
            "-gpu",str(args.gpu),"-bf","0","-rc-lookahead","0","-zerolatency","1","-delay","0","-g","30","-b:v","6M",
            "-maxrate","6M","-bufsize","300k","-aud","1","-vsync","0","-flush_packets","1","-f","h264","pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=(args.run/"encoder.log").open("w"))

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
        now = current()
        last_seq = max(last_seq,now.get("last_input_seq",0) if now else 0)
        await ws.send_json({"kind":"welcome","seq_base":last_seq,"input_config":now["input_config"] if now else None})
        try:
            async for item in ws:
                if item.type == web.WSMsgType.TEXT:
                    received_ns = time.monotonic_ns()
                    message = json.loads(item.data)
                    if message.get("kind") == "probe-clock":
                        # Measurement only: do not renew the control lease or consume a seq.
                        await ws.send_json({"kind":"probe-clock", "id":message["id"],
                                            "server_received_ns":received_ns,
                                            "server_sent_ns":time.monotonic_ns()})
                    elif message.get("kind") == "heartbeat":
                        forward({"kind":"heartbeat", "seq":last_seq})
                    elif message.get("kind") == "ping":
                        forward({"kind":"heartbeat", "seq":last_seq})
                        await ws.send_json({"kind":"pong","id":message["id"]})
                    else:
                        forward(message)
        finally:
            control_peers.discard(ws)
            last_seq += 1
            if physics.poll() is None:
                forward({"kind":"disconnect","seq":last_seq})
        return ws

    async def video(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        clients[ws] = True
        try:
            async for _ in ws:
                pass
        finally:
            clients.pop(ws,None)
        return ws

    async def health(request):
        now = current()
        return web.json_response({"run":args.run.name,"ready":bool(now) and physics.poll() is None and (renderer is None or renderer.poll() is None),"physics_alive":physics.poll() is None,
                                  "renderer_alive":renderer.poll() is None if renderer else None})

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
                        await asyncio.wait_for(ws.send_bytes(message),.05)
                    except (asyncio.TimeoutError,ConnectionError,RuntimeError):
                        await ws.close()
                        clients.pop(ws,None)
                metrics.write(json.dumps({"frame_id":metadata["frame_id"],"step":metadata["step"],
                                          "encode_ns":metadata["encode_ns"],"send_ns":time.monotonic_ns()-send_start,
                                          "bytes":len(message),"clients":len(clients)})+"\n")

    app = web.Application()
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM,stopped.set)
    loop.add_signal_handler(signal.SIGINT,stopped.set)
    async def shutdown(request):
        if request.query.get("run") != args.run.name:
            raise web.HTTPConflict(text="different run")
        stopped.set()
        return web.json_response({"stopping":True})
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
    app.router.add_get("/",lambda request:web.FileResponse(ROOT/"teleop/web/index.html"))
    app.router.add_static("/web/",ROOT/"teleop/web")
    app.router.add_static("/viewer/gamepad_overlay/",ROOT/"viewer/gamepad_overlay")
    runner = web.AppRunner(app)
    tasks = []
    try:
        await runner.setup()
        await web.TCPSite(runner,"127.0.0.1",args.port).start()
        tasks = [] if args.stream_off else [asyncio.create_task(raw_writer()),asyncio.create_task(encoded_reader())]
        while physics.poll() is None and not stopped.is_set():
            if renderer is not None and renderer.poll() is not None:
                raise worker_failure(renderer,"renderer.log")
            for task in tasks:
                if task.done():
                    task.result()
                    raise RuntimeError("encoder task exited; see encoder.log")
            await asyncio.sleep(.2)
        if not stopped.is_set() and physics.poll() is not None:
            if args.steps is None or physics.returncode != 0:
                raise worker_failure(physics,"physics.log")
    finally:
        for ws in list(clients)+list(control_peers):
            await ws.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            child.wait(timeout=10)
        if ffmpeg and ffmpeg.returncode is None:
            ffmpeg.stdin.close()
            try:
                await asyncio.wait_for(ffmpeg.wait(),5)
            except asyncio.TimeoutError:
                ffmpeg.kill()
                await ffmpeg.wait()
        await runner.cleanup()
        snapshot.close(); frames.close(); sock.close(); metrics.close()
        for log in logs:
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--config",type=Path,default=ROOT/"configs/teleop_gripper.yaml")
    parser.add_argument("--port",type=int,default=int(require("TELEOP_REMOTE_PORT")))
    parser.add_argument("--gpu",type=int,default=0)
    parser.add_argument("--steps",type=int)
    parser.add_argument("--commands",type=Path)
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
