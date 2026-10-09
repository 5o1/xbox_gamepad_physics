"""Command-line inspection and explicit RoboTwin asset installation."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Sequence

from .errors import XboxGamepadPhysicsError
from .profiles import load_profile, require_physics_ready


_BACKENDS = ("robotwin", "mujoco")


def _selected_backends(value: str) -> tuple[str, ...]:
    return _BACKENDS if value == "all" else (value,)


def _status(args: argparse.Namespace) -> int:
    profiles = [
        load_profile(backend, args.profile)
        for backend in _selected_backends(args.backend)
    ]
    if args.json:
        payload = []
        for profile in profiles:
            item = asdict(profile)
            item["manifest_path"] = str(item["manifest_path"])
            item["physics_ready"] = profile.physics_ready
            payload.append(item)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    for profile in profiles:
        state = "ready" if profile.physics_ready else "blocked"
        print(f"{profile.backend}/{profile.profile}: {state}")
        print(f"  available: {str(profile.available).lower()}")
        print(f"  dynamics_ready: {str(profile.dynamics_ready).lower()}")
        print(f"  entrypoint: {profile.entrypoint}")
        if profile.reason:
            print(f"  reason: {profile.reason}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    selected = _selected_backends(args.backend)
    for backend in selected:
        profile = require_physics_ready(backend, args.profile)
        print(
            f"{backend}/{args.profile}: ready "
            f"({len(profile.required_files)} required files)"
        )
    return 0


def _install_robotwin(args: argparse.Namespace) -> int:
    from .robotwin import install_native_assets

    result = install_native_assets(
        Path(args.root),
        args.profile,
        dry_run=not args.apply,
        overwrite=args.overwrite,
    )
    mode = "copy" if args.apply else "dry-run"
    print(f"RoboTwin native asset installation ({mode})")
    for operation in result.operations:
        print(f"  {operation.source} -> {operation.destination}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xbox-gamepad-physics",
        description="Inspect or load the packaged Xbox One S physical asset.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser(
        "status", help="show declared backend artifact readiness"
    )
    status.add_argument(
        "--backend", choices=(*_BACKENDS, "all"), default="all"
    )
    status.add_argument("--profile", default="full_controls")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=_status)

    verify = subparsers.add_parser(
        "verify", help="fail unless declared backend artifacts are complete"
    )
    verify.add_argument(
        "--backend", choices=(*_BACKENDS, "all"), default="all"
    )
    verify.add_argument("--profile", default="full_controls")
    verify.set_defaults(handler=_verify)

    install = subparsers.add_parser(
        "install-robotwin",
        help="inspect or copy ready resources into a RoboTwin checkout",
    )
    install.add_argument("--root", required=True)
    install.add_argument("--profile", default="full_controls")
    install.add_argument(
        "--apply",
        action="store_true",
        help="perform the copy; omission keeps the command read-only",
    )
    install.add_argument("--overwrite", action="store_true")
    install.set_defaults(handler=_install_robotwin)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and convert project errors to exit 2."""

    args = _parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except XboxGamepadPhysicsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
