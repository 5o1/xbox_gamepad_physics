"""Loopback-only viewer; serve only explicit asset/vendor/viewer roots."""
import argparse
import hashlib
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


def validate_asset_variant(project, assets, variant_id):
    registry_path = project / "assets" / "asset_index.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    active = registry.get("interactive_viewer", {}).get("active_variant_id")
    if variant_id != active:
        raise ValueError(f"variant {variant_id!r} is not the registry's active viewer variant {active!r}")
    variant = registry.get("derived_variants", {}).get(variant_id)
    if not isinstance(variant, dict):
        raise ValueError(f"variant absent from registry: {variant_id}")
    inventory = assets / "inventory.json"
    if not inventory.is_file():
        raise ValueError(f"missing fixture inventory: {inventory}")
    actual = hashlib.sha256(inventory.read_bytes()).hexdigest()
    expected = variant.get("inventory_sha256")
    if actual != expected:
        raise ValueError(f"inventory SHA-256 {actual} does not match {variant_id} ({expected})")
    return registry, variant


def validate_vendor(project, vendor):
    record_path = project / "sources" / "viewer_design.json"
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
    def __init__(self, *args, roots, **kwargs):
        self.roots = roots
        super().__init__(*args, **kwargs)

    def translate_path(self, path):
        path = unquote(urlsplit(path).path)
        route = next(
            (
                prefix
                for prefix in ("/assets/", "/vendor/", "/reference/", "/registry/")
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
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    try:
        validate_asset_variant(project, args.assets, args.variant_id)
        validate_vendor(project, args.vendor)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Asset identity validation failed: {error}")
    roots = {
        "/": project / "viewer",
        "/assets/": args.assets,
        "/vendor/": args.vendor,
        # Only expose the reviewed front-reference directory, not all results.
        "/reference/": project / "results" / "legacy_casper_1914_visual_parts",
        # Canonical IDs used to prove which asset variant the viewer received.
        "/registry/": project / "assets",
    }
    if not all(p.is_dir() for p in roots.values()):
        raise SystemExit("Missing required directory")
    print(f"Viewer http://127.0.0.1:{args.port}/ variant={args.variant_id}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, roots=roots)).serve_forever()
