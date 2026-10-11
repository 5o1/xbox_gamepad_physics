"""Build the explicit resource DAG using private content-based stamps."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from xbox_gamepad_physics._resource_cache import cache_lock, publish_directory
from xbox_gamepad_physics.errors import ResourceError

# Output directory of each node, relative to the resource root.
RESOURCE_OUTPUTS = {
    "kinematics": "kinematics",
    "common_motion": "common/xbox_one_s/motion",
    "sim_visual": "common/xbox_one_s/visual",
    "collision": "common/xbox_one_s/collision",
    "robotwin_left_stick": "robotwin/left_stick",
    "robotwin_full_controls": "robotwin/full_controls",
    "mujoco_frozen": "mujoco",
}


@dataclass(frozen=True)
class Node:
    name: str
    inputs: tuple[str, ...]
    upstream: tuple[str, ...]
    output: str
    generate: Callable[[Path, Path], None]
    sources: tuple[str, ...] = ()


def _generator(module: str, output: Path, **kwargs):
    # The script directory is needed by the existing generators' helper imports.
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    with redirect_stdout(sys.stderr):
        importlib.import_module(module).build(output=output, **kwargs)


def nodes(repo: Path = ROOT) -> tuple[Node, ...]:
    def kin(root):
        return root / "kinematics/xbox_one_s.json"
    def visual(root):
        return root / "common/xbox_one_s/visual"
    return (
        Node("kinematics", (
            "assets/xbox_one_s/visual/inventory.json",
            "references/xbox_one_s_artist_animation_summary.json",
            "references/1708_dimensions.json", "references/stick_envelope.json",
            "references/catalog.json",
        ), (), RESOURCE_OUTPUTS["kinematics"],
             lambda out, root: _generator("build_kinematics", out),
             ("scripts/build_kinematics.py", "scripts/asset_spec.py")),
        Node("common_motion", ("references/full_controls.json",), ("kinematics",),
             RESOURCE_OUTPUTS["common_motion"],
             lambda out, root: _generator("build_common_motion", out / "full_controls.json", kinematics=kin(root)),
             ("scripts/build_common_motion.py", "src/xbox_gamepad_physics/state.py")),
        Node("sim_visual", (
            "assets/xbox_one_s/source/xbox_one_s_controllergamepad_animated.glb",
            "assets/xbox_one_s/visual/Xbox_One_S_BatonyRobson_STATIC_VISUAL_UNCALIBRATED.glb",
            "assets/xbox_one_s/visual/inventory.json",
        ), ("kinematics",), RESOURCE_OUTPUTS["sim_visual"],
             lambda out, root: _generator("export_sim_visual_assets", out, kinematics=kin(root)),
             ("scripts/export_sim_visual_assets.py",)),
        Node("collision", ("assets/xbox_one_s/collision_meshbase", "references/full_controls.json"),
             (), RESOURCE_OUTPUTS["collision"],
             lambda out, root: _generator("build_common_collision", out,
                                          meshbase=repo / "assets/xbox_one_s/collision_meshbase",
                                          policy=repo / "references/full_controls.json"),
             ("scripts/build_common_collision.py",)),
        Node("robotwin_left_stick", ("references/left_stick.json",),
             ("kinematics", "sim_visual"), RESOURCE_OUTPUTS["robotwin_left_stick"],
             lambda out, root: _generator("build_robotwin_left_stick", out, kinematics=kin(root), visual_manifest=visual(root) / "manifest.json"),
             ("scripts/build_robotwin_left_stick.py",)),
        Node("robotwin_full_controls", ("references/full_controls.json", "references/left_stick.json"),
             ("kinematics", "common_motion", "sim_visual", "collision"), RESOURCE_OUTPUTS["robotwin_full_controls"],
             lambda out, root: _generator("build_robotwin_full_controls", out, kinematics=kin(root), visual_root=visual(root), common_motion=root / "common/xbox_one_s/motion/full_controls.json", collision_root=root / RESOURCE_OUTPUTS["collision"]),
             ("scripts/build_robotwin_full_controls.py", "scripts/build_common_collision.py")),
        Node("mujoco_frozen", ("src/xbox_gamepad_physics/resource_data/mujoco",), (), RESOURCE_OUTPUTS["mujoco_frozen"],
             lambda out, root: shutil.copytree(repo / "src/xbox_gamepad_physics/resource_data/mujoco", out)),
    )


def _ordered(graph: tuple[Node, ...]) -> tuple[Node, ...]:
    remaining = {node.name: node for node in graph}
    if len(remaining) != len(graph):
        raise ResourceError("duplicate resource node name")
    ordered = []
    while remaining:
        ready = [node for node in remaining.values() if set(node.upstream) <= {n.name for n in ordered}]
        if not ready:
            raise ResourceError("resource graph contains a cycle or an unknown upstream node")
        for node in ready:
            ordered.append(node)
            del remaining[node.name]
    return tuple(ordered)


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.is_file())
    raise ResourceError(f"missing build input {path}; install the [build] extra and restore source assets")


def _fingerprint(node: Node, repo: Path, root: Path, table: dict[str, Node]) -> dict:
    result = {}
    for relative in (*node.inputs, *node.sources, "scripts/build_resources.py"):
        for path in _files(repo / relative):
            result["source/" + path.relative_to(repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in node.upstream:
        for path in _files(root / table[name].output):
            result["upstream/" + path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"inputs": result, "upstream": list(node.upstream), "output": node.output}


def _read_stamp(root: Path, node: Node) -> dict:
    try:
        return json.loads((root / ".stamps" / (node.name + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def node_status(root: Path, *, repo: Path = ROOT, graph: tuple[Node, ...] | None = None) -> list[dict]:
    graph = _ordered(nodes(repo) if graph is None else graph)
    table = {node.name: node for node in graph}
    stale = set()
    report = []
    for node in graph:
        stamp = _read_stamp(root, node)
        outputs = stamp.get("files", [])
        missing = [node.output + "/" + p for p in outputs if not (root / node.output / p).is_file()]
        if not outputs:
            missing = [node.output]
        try:
            changed = stamp.get("fingerprint") != _fingerprint(node, repo, root, table)
        except ResourceError:
            changed = True
        outdated = bool(changed or missing or stale.intersection(node.upstream))
        if outdated:
            stale.add(node.name)
        report.append({"name": node.name, "stale": outdated, "missing": missing})
    return report


def build(output: Path = ROOT / "build/resources", *, force: bool = False,
          repo: Path = ROOT, graph: tuple[Node, ...] | None = None) -> list[dict]:
    """Build stale nodes and all downstream nodes, publishing only on success."""
    started = time.perf_counter()
    output = Path(output).resolve()
    graph = _ordered(nodes(repo) if graph is None else graph)
    table = {node.name: node for node in graph}
    try:
        with cache_lock(output):
            statuses = node_status(output, repo=repo, graph=graph)
            selected = {s["name"] for s in statuses if force or s["stale"]}
            if not selected:
                for node in graph:
                    print(f"{node.name}: skip (stamp hit)", file=sys.stderr)
                print(f"resources: {time.perf_counter() - started:.3f}s", file=sys.stderr)
                return statuses
            with tempfile.TemporaryDirectory(prefix=output.name + ".stage-", dir=output.parent) as temporary:
                staged = Path(temporary) / "resources"
                if output.exists():
                    shutil.copytree(output, staged)
                else:
                    staged.mkdir()
                (staged / ".stamps").mkdir(exist_ok=True)
                for node in graph:
                    tick = time.perf_counter()
                    if node.name not in selected:
                        print(f"{node.name}: skip (stamp hit)", file=sys.stderr)
                        continue
                    destination = staged / node.output
                    if destination.exists():
                        shutil.rmtree(destination)
                    node.generate(destination, staged)
                    files = [p.relative_to(destination).as_posix() for p in _files(destination)]
                    stamp = {"fingerprint": _fingerprint(node, repo, staged, table), "files": files}
                    (staged / ".stamps" / (node.name + ".json")).write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
                    print(f"{node.name}: rebuild ({time.perf_counter() - tick:.3f}s)", file=sys.stderr)
                publish_directory(staged, output)
        print(f"resources: {time.perf_counter() - started:.3f}s", file=sys.stderr)
        return statuses
    except (ImportError, OSError, ValueError) as error:
        raise ResourceError(f"resource build failed: {error}; install xbox-gamepad-physics[build]") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/resources")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    build(args.output, force=args.force)


if __name__ == "__main__":
    main()
