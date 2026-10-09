"""Loopback-only viewer; serve only explicit asset/vendor/viewer roots."""
import argparse
import hashlib
import json
import shlex
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


def validate_asset_variant(project, assets, variant_id):
    registry_path = project / "assets" / "asset_index.json"
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
        if not isinstance(profile_binding, dict) or set(profile_binding) != {"path"}:
            raise ValueError(f"{variant_id}: viewer_profile must contain exactly one path")
        relative = profile_binding.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or Path(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in Path(relative).parts)
        ):
            raise ValueError(f"{variant_id}: unsafe viewer profile path")
        profile_root = (project / "assets").resolve()
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
            or not parameter_source.startswith("references/")
            or "\\" in parameter_source
            or Path(parameter_source).is_absolute()
            or any(part in {"", ".", ".."} for part in Path(parameter_source).parts)
        ):
            raise ValueError(f"{variant_id}: unsafe parameter source path")
        parameter_path = (project.resolve() / parameter_source).resolve()
        if not parameter_path.is_relative_to((project / "references").resolve()) or not parameter_path.is_file():
            raise ValueError(f"{variant_id}: missing parameter source")
    viewer_entry = variant.get("viewer_entry", viewer.get("entry"))
    if not isinstance(viewer_entry, str) or not viewer_entry:
        raise ValueError(f"{variant_id}: missing viewer entry")
    viewer_root = (project / "viewer").resolve()
    entry_path = (project / "assets" / viewer_entry).resolve()
    if not entry_path.is_relative_to(viewer_root) or not entry_path.is_file():
        raise ValueError(f"{variant_id}: unsafe or missing viewer entry")
    variant["_validated_viewer_url"] = "/" + entry_path.relative_to(viewer_root).as_posix()
    return registry, variant


def validate_vendor(project, vendor):
    record_path = project / "references" / "viewer_design.json"
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
    def __init__(self, *args, roots, cycles=None, **kwargs):
        self.roots = roots
        self.cycles = cycles
        super().__init__(*args, **kwargs)

    def do_POST(self):
        if self.path != '/cycles/frame' or self.cycles is None:
            self.send_error(404)
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
        route = next(
            (
                prefix
                for prefix in ("/assets/", "/source/", "/approved/", "/accepted-reference/", "/vendor/", "/reference/", "/candidate-reference/", "/registry/", "/evidence/")
                if path.startswith(prefix)
            ),
            "/",
        )
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--variant-id", required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--blender", default="blender", help="Blender 4.5 executable")
    parser.add_argument("--cycles-command", help="Explicit worker command, e.g. SSH to an existing Blender installation")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    try:
        _, variant = validate_asset_variant(project, args.assets, args.variant_id)
        validate_vendor(project, args.vendor)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Asset identity validation failed: {error}")
    roots = {
        "/": project / "viewer",
        "/assets/": args.assets,
        "/source/": project / "assets" / "xbox_one_s" / "source",
        "/approved/": project / "assets" / "xbox_one_s",
        "/accepted-reference/": project / "results/xbox_official_import_comparison/official_import_4.5.9_LTS/reference_matched_cycles_probe",
        "/vendor/": args.vendor,
        # Only expose the reviewed front-reference directory, not all results.
        "/reference/": project / "results" / "legacy_casper_1914_visual_parts",
        "/candidate-reference/": project / "results" / "xbox_one_s_batonyrobson_UNVERIFIED",
        # Canonical IDs used to prove which asset variant the viewer received.
        "/registry/": project / "assets",
        "/evidence/": project / "references",
    }
    if not all(p.is_dir() for p in roots.values()):
        raise SystemExit("Missing required directory")
    print(f"Viewer http://127.0.0.1:{args.port}{variant['_validated_viewer_url']} variant={args.variant_id}", flush=True)
    from cycles_bridge import CyclesBridge
    command = shlex.split(args.cycles_command) if args.cycles_command else [
        args.blender, '--background', str(project / 'assets/xbox_one_s/render/Xbox_One_S_approved_cycles.blend'),
        '--python', str(project / 'scripts/cycles_worker.py'),
    ]
    cycles = CyclesBridge(command)
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, roots=roots, cycles=cycles)).serve_forever()
    finally:
        cycles.close()
