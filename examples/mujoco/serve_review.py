"""Serve a MuJoCo video review with the project's existing canonical overlay."""
from __future__ import annotations

import argparse
from pathlib import Path

from xbox_gamepad_physics.web.server import create_overlay_server, serve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True,
                        help='Review directory containing index.html, videos and signals.')
    parser.add_argument('--port', type=int, default=8774)
    args = parser.parse_args()
    server = create_overlay_server(trace_dir=args.directory, port=args.port)
    server.entry_path = '/traces/index.html'
    serve(server, 'MuJoCo review + canonical overlay')


if __name__ == '__main__':
    main()
