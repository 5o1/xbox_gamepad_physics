"""Build the explicit resource DAG using private content-based stamps."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Callable

from .paths import DATA_ROOT, ROOT

BUILDER_ROOT = Path(__file__).resolve().parent
from xbox_gamepad_physics._resource_cache import cache_lock, publish_directory
from xbox_gamepad_physics.errors import ResourceError
from .usage import write_resource_readme
from xbox_gamepad_physics.backends.registry import backend_spec, selected_nodes

# Output directory of each node, relative to the resource root.
RESOURCE_OUTPUTS = {
    "kinematics": "kinematics",
    "common_motion": "common/xbox_one_s/motion",
    "sim_visual": "common/xbox_one_s/visual",
    "collision": "common/xbox_one_s/collision",
    "common_physical": "common/xbox_one_s/physical",
    "robotwin_left_stick": "robotwin/left_stick",
    "robotwin_full_controls": "robotwin/full_controls",
    "mujoco_full_controls": "mujoco/full_controls",
}


@dataclass(frozen=True)
class Node:
    name: str
    inputs: tuple[str, ...]
    upstream: tuple[str, ...]
    output: str
    generate: Callable[[Path, Path], None]
    sources: tuple[str, ...] = ()
    options: str = ""


def _generator(module: str, output: Path, **kwargs):
    with redirect_stdout(sys.stderr):
        importlib.import_module("." + module, __package__).build(output=output, **kwargs)


def nodes(inputs: Path, *, evidence: Path = DATA_ROOT, calibration=None) -> tuple[Node, ...]:
    """Build only from the imported input snapshot and wheel evidence."""
    from xbox_gamepad_physics.backends.common.calibration import load_calibration, resolve_calibration, ResolvedCalibration
    if not isinstance(calibration, ResolvedCalibration):
        override = load_calibration(calibration)
        calibration = resolve_calibration(override=override, profile=override.profile)
    inputs, evidence = Path(inputs).resolve(), Path(evidence).resolve()
    def calibrated(profile):
        return calibration if calibration.profile == profile else None
    physical_sources = tuple(str(BUILDER_ROOT.parent / "backends/common" / name)
                             for name in ("model.py", "calibration.py", "physical.py"))
    adapter_source = str(BUILDER_ROOT.parent / "robotwin/physical.py")
    options = json.dumps(asdict(calibration), sort_keys=True)
    def physical_builder(out, root):
        from xbox_gamepad_physics.backends.common.physical import build as generate
        generate(out, full_controls_source=evidence / "references/full_controls.json",
                 left_stick_source=evidence / "references/left_stick.json",
                 common_motion=root / "common/xbox_one_s/motion/full_controls.json",
                 kinematics=kin(root), meshbase=meshbase,
                 collision_root=root / RESOURCE_OUTPUTS["collision"], calibration=calibration)
    def asset(relative):
        return str(inputs / relative)
    def proof(relative):
        return str(evidence / relative)
    def code(*names):
        return tuple(str(BUILDER_ROOT / (name + ".py")) for name in names)
    def kin(root):
        return root / "kinematics/xbox_one_s.json"
    def visual(root):
        return root / "common/xbox_one_s/visual"
    meshbase = inputs / "assets/xbox_one_s/collision_meshbase"
    policy = evidence / "references/full_controls.json"
    from xbox_gamepad_physics.mujoco.builder import resource_node
    from xbox_gamepad_physics.backends.registry import MUJOCO_RELEASE_GUIDANCE
    from .usage import document_dependency
    from dataclasses import replace
    mujoco_node = resource_node()
    def generate_mujoco(out, root):
        mujoco_node.generate(out, root)
        document_dependency(out, MUJOCO_RELEASE_GUIDANCE)
    return (
        replace(mujoco_node, generate=generate_mujoco),
        Node("kinematics", (
            asset("assets/xbox_one_s/visual/inventory.json"),
            proof("references/xbox_one_s_artist_animation_summary.json"),
            proof("references/1708_dimensions.json"), proof("references/stick_envelope.json"),
            proof("references/catalog.json"), proof("assets/asset_index.json"),
        ), (), RESOURCE_OUTPUTS["kinematics"],
             lambda out, root: _generator("build_kinematics", out, inputs=inputs, evidence=evidence),
             code("build_kinematics", "asset_spec", "paths")),
        Node("common_motion", (str(policy),), ("kinematics",),
             RESOURCE_OUTPUTS["common_motion"],
             lambda out, root: _generator("build_common_motion", out / "full_controls.json", kinematics=kin(root), source=policy),
             (*code("build_common_motion"), str(BUILDER_ROOT.parent / "state.py"))),
        Node("sim_visual", (
            asset("assets/xbox_one_s/source/xbox_one_s_controllergamepad_animated.glb"),
            asset("assets/xbox_one_s/visual/Xbox_One_S_BatonyRobson_STATIC_VISUAL_UNCALIBRATED.glb"),
            asset("assets/xbox_one_s/visual/inventory.json"),
            asset("assets/xbox_one_s/visual_meshbase/visual_meshbase.glb"),
            asset("assets/xbox_one_s/visual_meshbase/materials.json"),
            asset("assets/xbox_one_s/visual_meshbase/manifest.json"),
        ), ("kinematics",), RESOURCE_OUTPUTS["sim_visual"],
             lambda out, root: _generator("export_sim_visual_assets", out, kinematics=kin(root), inputs=inputs),
             (*code("export_sim_visual_assets"), *(str(BUILDER_ROOT.parent / "backends/common" / name) for name in ("appearance.py", "model.py")))),
        Node("collision", (str(meshbase), asset("assets/xbox_one_s/collision_coacd"), str(policy)),
             (), RESOURCE_OUTPUTS["collision"],
             lambda out, root: _generator("common_collision", out, meshbase=meshbase,
                                          frozen=inputs / "assets/xbox_one_s/collision_coacd", policy=policy),
             code("common_collision")),
        Node("common_physical", (str(policy), proof("references/left_stick.json"), str(meshbase)),
             ("kinematics", "common_motion", "collision"), RESOURCE_OUTPUTS["common_physical"],
             physical_builder, physical_sources, options),
        Node("robotwin_left_stick", (proof("references/left_stick.json"),),
             ("kinematics", "sim_visual", "common_physical"), RESOURCE_OUTPUTS["robotwin_left_stick"],
             lambda out, root: _generator("build_robotwin_left_stick", out, kinematics=kin(root), visual_manifest=visual(root) / "manifest.json", source=evidence / "references/left_stick.json", calibration=calibrated("left_stick")),
             (*code("build_robotwin_left_stick"), *physical_sources, adapter_source), options),
        Node("robotwin_full_controls", (str(policy), proof("references/left_stick.json"), str(meshbase)),
             ("kinematics", "common_motion", "sim_visual", "collision", "common_physical"), RESOURCE_OUTPUTS["robotwin_full_controls"],
             lambda out, root: _generator("build_robotwin_full_controls", out, kinematics=kin(root), visual_root=visual(root), common_motion=root / "common/xbox_one_s/motion/full_controls.json", collision_root=root / RESOURCE_OUTPUTS["collision"], meshbase=meshbase, source=policy, left_stick_source=evidence / "references/left_stick.json", calibration=calibrated("full_controls")),
             (*code("build_robotwin_full_controls", "common_collision"), *physical_sources, adapter_source), options),
    )


def _selected_graph(inputs, evidence, *, backends=("robotwin",), targets=None, runtime="python", calibration=None):
    selected = []
    for name in backends:
        declaration = backend_spec(name)
        declaration.require_builder_runtime(runtime)
        selected.extend(declaration.node_names)
    return selected_nodes(nodes(inputs, evidence=evidence, calibration=calibration),
                          tuple(selected) if targets is None else tuple(targets))


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
    for relative in (*node.inputs, *node.sources, str(Path(__file__).resolve()), str(BUILDER_ROOT / "usage.py")):
        for path in _files(repo / relative):
            # Logical names keep build receipts independent of installation paths.
            if path.is_relative_to(BUILDER_ROOT.parent):
                label = "package/" + path.relative_to(BUILDER_ROOT.parent).as_posix()
            elif path.is_relative_to(repo):
                label = "source/" + path.relative_to(repo).as_posix()
            else:
                # Explicit evidence overrides retain the same logical layout.
                parts = path.parts
                marker = next((i for i, part in enumerate(parts) if part in ("references", "assets", "specs")), len(parts)-1)
                label = "source/" + "/".join(parts[marker:])
            result[label] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in node.upstream:
        for path in _files(root / table[name].output):
            if path.name == "README.md":
                continue
            result["upstream/" + path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"inputs": result, "upstream": list(node.upstream), "output": node.output, "options": node.options}


def _read_stamp(root: Path, node: Node) -> dict:
    try:
        return json.loads((root / ".stamps" / (node.name + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def node_status(root: Path, *, inputs: Path | None = None, evidence: Path = DATA_ROOT,
                repo: Path | None = None, graph: tuple[Node, ...] | None = None,
                backends=("robotwin",), targets=None, runtime="python", calibration=None) -> list[dict]:
    root = Path(root).resolve()
    repo = Path(repo).resolve() if repo is not None else root / "inputs"
    inputs = Path(inputs).resolve() if inputs is not None else repo
    if graph is None and calibration is None and not os.environ.get("XBOX_GAMEPAD_PHYSICS_CALIBRATION"):
        selected_config = root / ".selected-calibration.json"
        if selected_config.is_file():
            from xbox_gamepad_physics.backends.common.calibration import resolved_from_dict
            calibration = resolved_from_dict(json.loads(selected_config.read_text()))
    if graph is None and "isaac" in backends:
        from ..backends.registry import backend_spec
        backend_spec("isaac").require_builder_runtime(runtime)
        raise ResourceError("The unified resource DAG does not author USD yet; inside AppLauncher use xbox_gamepad_physics.isaac.build_usd with prepared common inputs. See docs/isaac_backend.md.")
    graph = _ordered(_selected_graph(inputs, evidence, backends=backends, targets=targets, runtime=runtime, calibration=calibration) if graph is None else graph)
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
          inputs: Path | None = None, evidence: Path = DATA_ROOT,
          repo: Path | None = None, graph: tuple[Node, ...] | None = None,
          backends=("robotwin",), targets=None, runtime="python", calibration=None) -> list[dict]:
    """Build stale nodes and all downstream nodes, publishing only on success."""
    started = time.perf_counter()
    output = Path(output).resolve()
    repo = Path(repo).resolve() if repo is not None else output / "inputs"
    inputs = Path(inputs).resolve() if inputs is not None else repo
    configuration = calibration
    if graph is None:
        from xbox_gamepad_physics.backends.common.calibration import load_calibration, resolve_calibration, ResolvedCalibration, resolved_from_dict
        selected_config = output / ".selected-calibration.json"
        if calibration is None and not os.environ.get("XBOX_GAMEPAD_PHYSICS_CALIBRATION") and selected_config.is_file():
            configuration = resolved_from_dict(json.loads(selected_config.read_text()))
        elif not isinstance(calibration, ResolvedCalibration):
            override = load_calibration(calibration)
            configuration = resolve_calibration(override=override, profile=override.profile)
        calibration = configuration
    graph = _ordered(_selected_graph(inputs, evidence, backends=backends, targets=targets, runtime=runtime, calibration=calibration) if graph is None else graph)
    table = {node.name: node for node in graph}
    try:
        with cache_lock(output):
            statuses = node_status(output, repo=repo, graph=graph)
            selected = {s["name"] for s in statuses if force or s["stale"]}
            if not selected:
                write_resource_readme(output)
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
                write_resource_readme(staged)
                if configuration is not None:
                    (staged / ".selected-calibration.json").write_text(json.dumps(asdict(configuration), indent=2) + "\n")
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
    parser.add_argument("--backend", choices=("robotwin", "mujoco", "isaac"), default="robotwin")
    parser.add_argument("--target", action="append")
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--inputs", type=Path, default=ROOT)
    args = parser.parse_args()
    build(args.output, force=args.force, inputs=args.inputs, backends=(args.backend,),
          targets=args.target, calibration=args.calibration)


if __name__ == "__main__":
    main()
