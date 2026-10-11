"""Configuration, shared run context and reproducible experiment outputs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any

import yaml

from . import EXPERIMENTS
from .scene import create_scene


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class RunContext:
    output_dir: Path
    scene: Any
    gamepad: Any
    load_seconds: float = 0.0


def load_config(path: Path | str) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        cfg = yaml.safe_load(stream)
    if not isinstance(cfg, dict):
        raise ValueError("configuration must be a YAML mapping")
    return cfg


def apply_overrides(cfg: dict, overrides: list[str]) -> dict:
    for override in overrides:
        key, separator, value = override.partition("=")
        if not separator:
            raise ValueError(f"override must be key=value: {override!r}")
        parts = key.split(".")
        node = cfg
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"unknown configuration key: {key}")
            node = node[part]
        if not isinstance(node, dict) or parts[-1] not in node:
            raise KeyError(f"unknown configuration key: {key}")
        node[parts[-1]] = yaml.safe_load(value)
    return cfg


def _git(*args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def collect_meta(command: list[str]) -> dict:
    from xbox_gamepad_physics.resources import resource_root

    try:
        sapien_version = version("sapien")
    except PackageNotFoundError:
        sapien_version = None
    status = _git("status", "--porcelain")
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(status) if status is not None else None,
        "python": platform.python_version(),
        "sapien": sapien_version,
        "resource_root": str(resource_root()),
        "command": command,
    }


def run_experiment(
    cfg: dict, config_path: Path | str, output_dir: Path | str | None = None,
    command: list[str] | None = None,
) -> dict:
    experiment = EXPERIMENTS[cfg["experiment"]]
    output = (
        Path(output_dir) if output_dir is not None else
        ROOT / "build/runs" / Path(config_path).stem / datetime.now().strftime("%Y%m%d-%H%M%S")
    ).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "config.yaml").write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8",
    )
    meta = collect_meta(command if command is not None else [sys.executable, *sys.argv])
    (output / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    from xbox_gamepad_physics.robotwin import load_into_scene

    previous_cwd = Path.cwd()
    try:
        scene = create_scene(cfg["scene"])
        tick = time.perf_counter()
        gamepad = load_into_scene(scene, profile=cfg["profile"], **cfg["gamepad"])
        load_seconds = time.perf_counter() - tick
        metrics = experiment(cfg, RunContext(output, scene, gamepad, load_seconds))
        (output / "metrics.json").write_text(
            json.dumps(metrics, indent=2) + "\n", encoding="utf-8",
        )
    finally:
        os.chdir(previous_cwd)
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--set", dest="overrides", nargs="+", action="extend", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        cfg = apply_overrides(load_config(args.config), args.overrides)
        if cfg["experiment"] not in EXPERIMENTS:
            raise ValueError(f"unknown experiment: {cfg['experiment']}")
        if cfg["scene"]["render"] and not cfg["scene"]["robotwin_root"]:
            raise ValueError("render requires scene.robotwin_root")
    except (KeyError, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    command = [sys.executable, *(sys.argv if argv is None else [str(ROOT / "run_robotwin.py"), *argv])]
    metrics = run_experiment(cfg, args.config, args.output, command)
    print(json.dumps(metrics))
    return 0 if metrics.get("passed", True) else 1
