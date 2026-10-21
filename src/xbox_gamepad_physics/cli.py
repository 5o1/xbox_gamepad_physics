"""Backend inspection, preparation and explicit RoboTwin asset installation."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Sequence

from .errors import XboxGamepadPhysicsError, ResourceNotFoundError
from .profiles import load_profile
from .resources import prepare_resources, resource_status
from .backends.registry import BACKENDS, backend_spec


_BACKENDS = tuple(BACKENDS)


def _selected_backends(value: str) -> tuple[str, ...]:
    if value == "all":
        return tuple(name for name,spec in BACKENDS.items() if spec.builder_runtime == "python")
    backend_spec(value).require_builder_runtime()
    return (value,)


def _status(args: argparse.Namespace) -> int:
    _selected_backends(args.backend)
    resources = resource_status(backends=_selected_backends(args.backend))
    if not args.json:
        _print_resources(resources)
    profiles = [
        load_profile(backend, args.profile)
        for backend in _selected_backends(args.backend)
    ]
    if args.json:
        payload = []
        for profile in profiles:
            item = asdict(profile)
            item["manifest_path"] = str(item["manifest_path"])
            item["resources"] = resources
            item["resource_root"] = resources["root"]
            payload.append(item)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    for profile in profiles:
        print(f"{profile.backend}/{profile.profile}:")
        print(f"  entrypoint: {profile.entrypoint}")
        if profile.default_collision:
            print(f"  default_collision: {profile.default_collision}")
            print(f"  min_sapien: {profile.min_sapien}")
        if profile.reason:
            print(f"  reason: {profile.reason}")
    return 0


def _print_resources(value: dict) -> None:
    print(f"resource root: {value['root']} ({value['mode']})")
    for node in value["nodes"]:
        print(f"  {node['name']}: {'stale' if node['stale'] else 'current'}")
    print("  missing: " + (", ".join(value["missing"]) or "none"))


def _build_resources(args: argparse.Namespace) -> int:
    print(f"resource root: {prepare_resources(force=args.force, archive=args.archive, resources=args.resources, offline=args.offline, backends=(args.backend,), targets=args.target, calibration=args.calibration)}")
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


def _export_example(args):
    from .examples.export import export_example
    print(f"example exported: {export_example(args.directory)}")
    return 0


def _guide(args):
    from .integration import GUIDE, MUJOCO_GUIDE, ISAAC_GUIDE, BACKEND_ENTRIES
    if args.backend is None:
        print(BACKEND_ENTRIES)
        print(GUIDE)
    else:
        for name, guide in (("robotwin", GUIDE), ("mujoco", MUJOCO_GUIDE), ("isaac", ISAAC_GUIDE)):
            if args.backend in {name, "all"}:
                print(guide)
    return 0


def _doctor(args):
    from .integration import diagnose_environment
    selected = tuple(BACKENDS) if args.backend == "all" else (args.backend,)
    result = diagnose_environment(backends=selected)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Python: {result['python']}")
        for name, version in result['versions'].items():
            print(f"{name}: {version or 'not installed'}")
        print("Resources: " + json.dumps(result['resources']))
        for extra, versions in result['extras'].items():
            print(f"[{extra}]: " + json.dumps(versions))
        for issue in result['issues']:
            print(issue)
        print("Next: xbox-gamepad-physics guide --backend NAME")
    return 1 if result['issues'] else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xbox-gamepad-physics",
        description="Start with guide and example export DIRECTORY. Inspect or load the packaged Xbox One S physical asset.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    guide = subparsers.add_parser("guide", help="read the integration guide")
    guide.add_argument("--backend", choices=("robotwin", "mujoco", "isaac", "all"), default=None)
    guide.set_defaults(handler=_guide)
    doctor = subparsers.add_parser("doctor", help="inspect Python, engine versions, extras and resource files")
    doctor.add_argument("--backend", choices=(*_BACKENDS, "all"), default="robotwin")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=_doctor)

    build = subparsers.add_parser("build-resources", help="build stale project-local resources")
    build.add_argument("--force", action="store_true")
    build.add_argument("--backend", choices=_BACKENDS, default="robotwin")
    build.add_argument("--target", action="append")
    build.add_argument("--calibration", type=Path)
    build.add_argument("--archive", type=Path, help="import the matching input zip")
    build.add_argument("--resources", type=Path, help="writable local resource root")
    build.add_argument("--offline", action="store_true", help="never download inputs")
    build.set_defaults(handler=_build_resources)

    status = subparsers.add_parser(
        "status", help="show backend entrypoints and resource files"
    )
    status.add_argument(
        "--backend", choices=(*_BACKENDS, "all"), default="all"
    )
    status.add_argument("--profile", default="full_controls")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=_status)

    install = subparsers.add_parser(
        "install-robotwin",
        help="inspect or copy generated resources into a RoboTwin checkout",
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
    example = subparsers.add_parser("example", help="export standalone RoboTwin examples")
    commands = example.add_subparsers(dest="example_command", required=True)
    export = commands.add_parser("export", help="export runner and two YAML files")
    export.add_argument("directory", type=Path)
    export.set_defaults(handler=_export_example)
    from .teleop.launch import add_arguments, add_replay_arguments
    add_arguments(subparsers.add_parser("teleop", help="local GPU teleoperation; optional SSH remote mode"))
    add_replay_arguments(subparsers.add_parser("teleop-replay", help="replay schema 3–6 commands in a fresh scene"))
    from .web.server import add_viewer_arguments, add_overlay_arguments, viewer_command, overlay_command
    viewer = subparsers.add_parser("viewer", help="start the installed Cycles viewer")
    add_viewer_arguments(viewer)
    viewer.set_defaults(handler=viewer_command)
    overlay = subparsers.add_parser("overlay", help="start the installed canonical overlay")
    add_overlay_arguments(overlay)
    overlay.set_defaults(handler=overlay_command)
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
