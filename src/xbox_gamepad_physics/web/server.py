"""Loopback HTTP services with only installed/static and explicit input roots."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xbox_gamepad_physics.errors import ResourceError
from xbox_gamepad_physics.resources import prepare_inputs
from xbox_gamepad_physics.builders.paths import DATA_ROOT
from .cycles_bridge import CyclesBridge
from xbox_gamepad_physics.gpu import gpu_environment

WEB_DATA = Path(__file__).resolve().parent / "static"
UI_ROOT = WEB_DATA / "ui"
REFERENCE_NAME = "boiler_room_vertical_fov35_strength_1p0.png"
REFERENCE_INPUT = "assets/xbox_one_s/render/" + REFERENCE_NAME

def validate_asset_variant(project, assets, variant_id, *, registry_path=None, generated_root=None, viewer_root=None):
    registry_path = registry_path or project / "assets" / "asset_index.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    viewer = registry.get("interactive_viewer", {})
    active = viewer.get("active_variant_id")
    allowed = viewer.get("allowed_variant_ids", [])
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise ValueError("interactive_viewer.allowed_variant_ids must be a string list")
    if variant_id != active and variant_id not in allowed:
        raise ValueError(
            f"variant {variant_id!r} is not the registry's active viewer variant "
            f"{active!r} or an explicitly allowed variant"
        )
    variant = registry.get("derived_variants", {}).get(variant_id)
    if not isinstance(variant, dict):
        raise ValueError(f"variant absent from registry: {variant_id}")
    inventory = assets / "inventory.json"
    if not inventory.is_file():
        raise ValueError(f"missing fixture inventory: {inventory}")
    profile_binding = variant.get("viewer_profile")
    if profile_binding is not None:
        if not isinstance(profile_binding, dict) or set(profile_binding) != {"route"}:
            raise ValueError(f"{variant_id}: viewer_profile must contain exactly one route")
        route = profile_binding.get("route")
        if (
            not isinstance(route, str)
            or not route.startswith("/generated/")
            or "\\" in route
        ):
            raise ValueError(f"{variant_id}: unsafe viewer profile route")
        relative = route.removeprefix("/generated/")
        if any(part in {"", ".", ".."} for part in Path(relative).parts):
            raise ValueError(f"{variant_id}: unsafe viewer profile route")
        profile_root = (generated_root or project / "build" / "generated").resolve()
        profile_path = (profile_root / relative).resolve()
        if not profile_path.is_relative_to(profile_root) or not profile_path.is_file():
            raise ValueError(f"{variant_id}: missing viewer profile")
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if profile.get("schema_version") != 2 or profile.get("variant_id") != variant_id:
            raise ValueError(f"{variant_id}: viewer profile identity/schema mismatch")
        visual = profile.get("visual", {})
        visual_file = visual.get("file")
        if (
            not isinstance(visual_file, str)
            or not visual_file
            or "\\" in visual_file
            or Path(visual_file).is_absolute()
            or any(part in {"", ".", ".."} for part in Path(visual_file).parts)
        ):
            raise ValueError(f"{variant_id}: unsafe visual container path")
        visual_path = (assets.resolve() / visual_file).resolve()
        if not visual_path.is_relative_to(assets.resolve()) or not visual_path.is_file():
            raise ValueError(f"{variant_id}: missing visual container")
        if hashlib.sha256(visual_path.read_bytes()).hexdigest() != visual.get("sha256"):
            raise ValueError(f"{variant_id}: visual container SHA-256 does not match")
        parameter_source = profile.get("parameter_source")
        if (
            not isinstance(parameter_source, str)
            or not parameter_source.startswith("/generated/")
            or "\\" in parameter_source
        ):
            raise ValueError(f"{variant_id}: unsafe parameter source path")
        parameter_relative = parameter_source.removeprefix("/generated/")
        if any(part in {"", ".", ".."} for part in Path(parameter_relative).parts):
            raise ValueError(f"{variant_id}: unsafe parameter source path")
        parameter_path = (profile_root / parameter_relative).resolve()
        if not parameter_path.is_relative_to(profile_root) or not parameter_path.is_file():
            raise ValueError(f"{variant_id}: missing parameter source")
        variant["_validated_profile_url"] = route
    viewer_entry = variant.get("viewer_entry", viewer.get("entry"))
    if not isinstance(viewer_entry, str) or not viewer_entry:
        raise ValueError(f"{variant_id}: missing viewer entry")
    if viewer_root is None:
        viewer_root = (project / "viewer").resolve()
        entry_path = (project / "assets" / viewer_entry).resolve()
    else:
        viewer_root = Path(viewer_root).resolve()
        if not viewer_entry.startswith("../viewer/"):
            raise ValueError(f"{variant_id}: unsafe viewer entry")
        entry_path = (viewer_root / viewer_entry.removeprefix("../viewer/")).resolve()
    if not entry_path.is_relative_to(viewer_root) or not entry_path.is_file():
        raise ValueError(f"{variant_id}: unsafe or missing viewer entry")
    variant["_validated_viewer_url"] = "/" + entry_path.relative_to(viewer_root).as_posix()
    return registry, variant


def validate_vendor(project, vendor, *, record_path=None):
    record_path = record_path or project / "references" / "viewer_design.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    dependency = record.get("dependencies", {})
    expected_version = dependency.get("three")
    expected_files = dependency.get("extracted_files")
    if not isinstance(expected_version, str) or not isinstance(expected_files, dict):
        raise ValueError(f"{record_path}: incomplete Three.js identity record")
    vendor_root = vendor.resolve()
    package_path = (vendor_root / "package.json").resolve()
    if not package_path.is_relative_to(vendor_root) or not package_path.is_file():
        raise ValueError("missing or unsafe vendor file: package.json")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package.get("name") != "three" or package.get("version") != expected_version:
        raise ValueError(
            f"vendor package identity is {package.get('name')!r} {package.get('version')!r}; "
            f"expected 'three' {expected_version!r}"
        )
    for relative, expected_hash in expected_files.items():
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise ValueError(f"{record_path}: invalid extracted file record")
        target = (vendor_root / relative).resolve()
        if not target.is_relative_to(vendor_root) or not target.is_file():
            raise ValueError(f"missing or unsafe vendor file: {relative}")
        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"vendor file SHA-256 {actual_hash} does not match {relative} ({expected_hash})"
            )
    return expected_version


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, roots, cycles=None, cycles_error=None, **kwargs):
        self.roots = roots
        self.cycles = cycles
        self.cycles_error = cycles_error
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if urlsplit(self.path).path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if (urlsplit(self.path).path == "/accepted-reference/" + REFERENCE_NAME
                and not Path(self.translate_path(self.path)).is_file()):
            # Keep the image slot usable even when this optional input is absent.
            image = ('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="340" '
                     'viewBox="0 0 600 340" role="img" aria-label="缺少输入资源">'
                     '<rect width="600" height="340" fill="#252b34"/>'
                     '<text x="300" y="170" text-anchor="middle" fill="#f5c97b" '
                     'font-family="sans-serif" font-size="28">缺少输入资源</text></svg>').encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(image)))
            self.end_headers()
            self.wfile.write(image)
            return
        super().do_GET()

    def do_POST(self):
        if self.path != '/cycles/frame':
            self.send_error(404)
            return
        if self.cycles is None:
            self.send_error(503, self.cycles_error or "Cycles unavailable: provide --blender with a Blender 4.5 executable")
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 32768:
                raise ValueError('invalid request size')
            frame = self.cycles.render(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as error:
            self.send_error(500, str(error))

    def translate_path(self, path):
        path = unquote(urlsplit(path).path)
        route = next((prefix for prefix in sorted(self.roots, key=len, reverse=True)
                      if prefix != "/" and path.startswith(prefix)), "/")
        root = self.roots[route].resolve()
        target = (root / path[len(route):]).resolve()
        if not target.is_relative_to(root):
            return str(root / "__denied__")
        return str(target)

    def list_directory(self, path):
        self.send_error(403, "Directory listing disabled")

    def log_message(self, format, *args):
        # An SSH session's logging pipe may disappear while the server lives.
        # Logging failure must not abort send_response before headers are sent.
        try:
            super().log_message(format, *args)
        except (OSError, ValueError):
            pass

def create_viewer_server(*, resources=None, archive=None, offline=False, blender=None, port=8766, gpu=0):
    """Cycles selects --gpu in the caller's visible list, just like teleop."""
    worker_env = gpu_environment(gpu) if blender else None
    root, inputs = prepare_inputs(resources=resources, archive=archive, offline=offline,
                                  optional_files=(REFERENCE_INPUT,))
    from xbox_gamepad_physics.builders.build_resources import build, nodes
    # Reuse the same kinematics DAG node; no separate viewer generation tree.
    build(root, inputs=inputs, graph=(nodes(inputs)[0],))
    assets = inputs / "assets/xbox_one_s/visual"
    _, variant = validate_asset_variant(root, assets, "xbox_one_s",
        registry_path=DATA_ROOT / "assets/asset_index.json", generated_root=root,
        viewer_root=UI_ROOT)
    vendor = WEB_DATA / "vendor/three"
    validate_vendor(root, vendor, record_path=WEB_DATA / "viewer_design.json")
    roots = {"/": UI_ROOT, "/viewer/": UI_ROOT, "/assets/": assets,
        "/source/": inputs / "assets/xbox_one_s/source",
        "/approved/": inputs / "assets/xbox_one_s",
        "/accepted-reference/": inputs / "assets/xbox_one_s/render", "/generated/": root,
        "/vendor/": vendor, "/registry/": DATA_ROOT / "assets",
        "/evidence/": DATA_ROOT / "references"}
    cycles = None
    error = "Cycles unavailable: provide --blender with a Blender 4.5 executable"
    if blender:
        try:
            cycles = CyclesBridge([str(blender), "--background",
                str(inputs / "assets/xbox_one_s/render/Xbox_One_S_approved_cycles.blend"),
                "--python", str(Path(__file__).with_name("cycles_worker.py"))], env=worker_env)
        except OSError as failure:
            error = f"Cycles unavailable: {failure}; provide --blender with Blender 4.5"
    if cycles is None:
        print(error, file=sys.stderr, flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, roots=roots,
                                 cycles=cycles, cycles_error=error))
    server.cycles = cycles
    server.entry_path = variant["_validated_viewer_url"]
    return server


def create_overlay_server(*, trace_dir=None, port=8770):
    roots = {"/": UI_ROOT, "/viewer/": UI_ROOT,
             "/demo/": UI_ROOT / "gamepad_overlay/demo"}
    if trace_dir is not None:
        trace_dir = Path(trace_dir).expanduser().resolve(strict=True)
        if not trace_dir.is_dir():
            raise ResourceError("trace directory must be a directory")
        roots["/traces/"] = trace_dir
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, roots=roots))
    server.cycles = None
    server.entry_path = "/viewer/gamepad_overlay/index.html?source=canonical&trace=/demo/trace.json&autoplay=1"
    return server


def serve(server, label):
    print(f"{label} http://127.0.0.1:{server.server_port}{server.entry_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if server.cycles is not None:
            server.cycles.close()


def add_viewer_arguments(parser):
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--blender", help="Blender 4.5 executable; absent worker reports HTTP503")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--gpu", type=int, default=0, help="调用者可见设备中的序号，默认0")


def viewer_command(args):
    try:
        serve(create_viewer_server(**{key:getattr(args,key) for key in ("resources","archive","offline","blender","port","gpu")}), "Viewer")
    except (ResourceError, OSError, ValueError) as error:
        print(f"viewer: {error}", file=sys.stderr)
        return 2
    return 0


def add_overlay_arguments(parser):
    parser.add_argument("--trace-dir", type=Path)
    parser.add_argument("--port", type=int, default=8770)


def overlay_command(args):
    try:
        serve(create_overlay_server(**{key:getattr(args,key) for key in ("trace_dir","port")}), "Overlay")
    except (ResourceError, OSError, ValueError) as error:
        print(f"overlay: {error}", file=sys.stderr)
        return 2
    return 0


def viewer_main(argv=None):
    parser=argparse.ArgumentParser(description="Installed Xbox One S Cycles viewer")
    add_viewer_arguments(parser)
    return viewer_command(parser.parse_args(argv))


def overlay_main(argv=None):
    parser=argparse.ArgumentParser(description="Canonical signal overlay with an included demo")
    add_overlay_arguments(parser)
    return overlay_command(parser.parse_args(argv))
