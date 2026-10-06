"""Loopback-only viewer; serve only explicit asset/vendor/viewer roots."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, roots, **kwargs):
        self.roots = roots
        super().__init__(*args, **kwargs)

    def translate_path(self, path):
        path = unquote(urlsplit(path).path)
        route = next((prefix for prefix in ("/assets/", "/vendor/") if path.startswith(prefix)), "/")
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
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    roots = {"/": Path(__file__).resolve().parents[1] / "viewer", "/assets/": args.assets, "/vendor/": args.vendor}
    if not all(p.is_dir() for p in roots.values()):
        raise SystemExit("Missing required directory")
    print(f"Viewer http://127.0.0.1:{args.port}/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, roots=roots)).serve_forever()
