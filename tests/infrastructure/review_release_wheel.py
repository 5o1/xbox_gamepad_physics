"""Audit release payloads against current source and the v0.4.2 Git tag.

Run with Python 3.11+ and setuptools from the repository root:
    python3 tests/infrastructure/review_release_wheel.py
"""
from __future__ import annotations

import argparse
import ast
import glob
import hashlib
from importlib.util import resolve_name
import json
from pathlib import Path
import runpy
import subprocess
from unittest.mock import patch
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
STALE_MEMBERS = (
    "xbox_gamepad_physics/acceptance/__init__.py",
    "xbox_gamepad_physics/acceptance/cases.py",
    "xbox_gamepad_physics/acceptance/performance.py",
    "xbox_gamepad_physics/acceptance/records.py",
    "xbox_gamepad_physics/acceptance/runner.py",
    "xbox_gamepad_physics/acceptance/scoring.py",
    "xbox_gamepad_physics/acceptance/views.py",
    "xbox_gamepad_physics/build_data/acceptance/ruling20_sdf303_v1.json",
    "xbox_gamepad_physics/build_data/specs/interactive_acceptance.json",
    "xbox_gamepad_physics/isaac/diagnostics.py",
    "xbox_gamepad_physics/isaac/press.py",
    "xbox_gamepad_physics/mujoco/_manifest.py",
    "xbox_gamepad_physics/mujoco/acceptance.py",
    "xbox_gamepad_physics/mujoco/visual.py",
    "xbox_gamepad_physics/teleop/ball_probe.py",
    "xbox_gamepad_physics/teleop/finger_validate.py",
    "xbox_gamepad_physics/teleop/validate.py",
)
STALE_MODULES = {
    name.removesuffix("/__init__.py").removesuffix(".py").replace("/", "."): name
    for name in STALE_MEMBERS if name.endswith(".py")
}


def stale_imports(root=ROOT):
    """Find actual import statements, resolving relative imports by package."""
    hits = []
    files = sorted(path for directory in ("src", "tests", "examples", "scripts")
                   for path in (root / directory).rglob("*.py"))
    for path in files:
        relative = path.relative_to(root)
        module_path = relative.relative_to("src") if relative.parts[0] == "src" else relative
        package = ".".join(module_path.parent.parts)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = resolve_name("." * node.level + base, package)
                names = [base, *(base + "." + alias.name for alias in node.names)]
            else:
                continue
            for module, member in STALE_MODULES.items():
                if any(name == module or name.startswith(module + ".") for name in names):
                    hits.append({"file": relative.as_posix(), "line": node.lineno,
                                 "import": ast.unparse(node), "module": module,
                                 "stale_member": member})
    return {"directories": ["src", "tests", "examples", "scripts"],
            "python_files_scanned": len(files), "hits": hits}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit(wheel, previous_wheel):
    import tomllib
    from setuptools import find_packages

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    setuptools = config["tool"]["setuptools"]
    where = setuptools["packages"]["find"]["where"]
    assert where == ["src"], "review package discovery if source roots change"
    packages = sorted(find_packages(where=str(ROOT / where[0])))
    # Execute the actual compatibility shim with only setup() intercepted.
    with patch("setuptools.setup") as setup:
        runpy.run_path(str(ROOT / "setup.py"))
    mirror = setup.call_args.kwargs
    mirror_checks = {
        "version": mirror["version"] == config["project"]["version"],
        "package_dir": mirror["package_dir"] == {"": where[0]},
        "packages": sorted(mirror["packages"]) == packages,
        "package_data": mirror["package_data"] == setuptools["package-data"],
        "include_package_data": mirror["include_package_data"] == setuptools["include-package-data"] is False,
        "extras": mirror["extras_require"] == config["project"]["optional-dependencies"],
        "entry_points": mirror["entry_points"]["console_scripts"] == [
            f"{name}={target}" for name, target in config["project"]["scripts"].items()],
    }
    expected = set()
    for package in packages:
        package_root = ROOT / "src" / package.replace(".", "/")
        expected.update(path.relative_to(ROOT / "src").as_posix()
                        for path in package_root.glob("*.py"))
        for pattern in setuptools["package-data"].get(package, []):
            expected.update(Path(name).relative_to(ROOT / "src").as_posix()
                            for name in glob.glob(str(package_root / pattern)) if Path(name).is_file())
    with ZipFile(wheel) as current, ZipFile(previous_wheel) as previous:
        actual = {name for name in current.namelist() if name.startswith("xbox_gamepad_physics/")}
        dist_info = (config["project"]["name"].replace("-", "_") + "-" +
                     config["project"]["version"] + ".dist-info/")
        expected_metadata = {dist_info + name for name in (
            "licenses/LICENSE", "METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD")}
        actual_metadata = set(current.namelist()) - actual
        license_identical = (dist_info + "licenses/LICENSE" in actual_metadata and
                             current.read(dist_info + "licenses/LICENSE") == (ROOT / "LICENSE").read_bytes())
        old = {name for name in previous.namelist() if name.startswith("xbox_gamepad_physics/")}
        payload = [{"file": name, "wheel_sha256": digest(current.read(name)),
                    "source_sha256": digest((ROOT / "src" / name).read_bytes()),
                    "identical": current.read(name) == (ROOT / "src" / name).read_bytes()}
                   for name in sorted(actual & expected)]
        isaac_paths = subprocess.check_output([
            "git", "ls-tree", "-r", "--name-only", "v0.4.2", "--",
            "src/xbox_gamepad_physics/isaac"], cwd=ROOT, text=True).splitlines()
        isaac = []
        for path in isaac_paths:
            if not path.endswith(".py"):
                continue
            name = path.removeprefix("src/")
            source = subprocess.check_output(["git", "show", "v0.4.2:" + path], cwd=ROOT)
            data = current.read(name)
            isaac.append({"file": name, "wheel_sha256": digest(data),
                          "v042_tag_source_sha256": digest(source), "identical": data == source})
        references = stale_imports()
        residuals = [{"file": name, "v042_wheel_sha256": digest(previous.read(name)),
                      "in_v043_wheel": name in actual,
                      "in_current_source": (ROOT / "src" / name).exists(),
                      "imports": [hit for hit in references["hits"] if hit["stale_member"] == name]}
                     for name in STALE_MEMBERS]
        report = {
            "release": config["project"]["version"],
            "wheel_sha256": digest(wheel.read_bytes()),
            "v042_wheel_sha256": digest(previous_wheel.read_bytes()),
            "source_of_expected_payload": "pyproject.toml package discovery/data, setup.py actual mirrored arguments, current src package Python files",
            "setup_py_mirror": mirror_checks, "packages": packages,
            "expected_package_files": len(expected), "actual_package_files": len(actual),
            "missing_package_files": sorted(expected - actual),
            "unexpected_package_files": sorted(actual - expected),
            "package_payload": payload,
            "expected_metadata_files": len(expected_metadata),
            "actual_metadata_files": len(actual_metadata),
            "missing_metadata_files": sorted(expected_metadata - actual_metadata),
            "unexpected_metadata_files": sorted(actual_metadata - expected_metadata),
            "license_matches_source": license_identical,
            "expected_wheel_files": len(expected | expected_metadata),
            "actual_wheel_files": len(current.namelist()),
            "metadata_files": [{"file": name, "sha256": digest(current.read(name))}
                               for name in current.namelist() if name not in actual],
            "isaac_comparison_basis": "git tag v0.4.2 source, not the historical wheel",
            "isaac_modules": isaac,
            "historical_residuals_match_exactly": old - actual == set(STALE_MEMBERS),
            "historical_residuals": residuals,
            "source_import_scan": references,
            "checkout_compatibility_wrapper": {
                "tests_import": "teleop.ball_probe",
                "wrapper": "teleop/ball_probe.py",
                "target": "tests.acceptance.robotwin.probe",
                "explanation": "This checkout-only top-level module is distinct from xbox_gamepad_physics.teleop.ball_probe.",
            },
        }
    report["accepted"] = (all(mirror_checks.values()) and not expected ^ actual
                          and expected_metadata == actual_metadata and license_identical
                          and report["expected_wheel_files"] == report["actual_wheel_files"]
                          and all(row["identical"] for row in payload)
                          and len(isaac) == 11 and all(row["identical"] for row in isaac)
                          and report["historical_residuals_match_exactly"]
                          and not any(row["in_current_source"] for row in residuals)
                          and not references["hits"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, default=ROOT / "build/release/v0.4.3/xbox_gamepad_physics-0.4.3-py3-none-any.whl")
    parser.add_argument("--previous-wheel", type=Path, default=ROOT / "build/release_v042/downloaded/xbox_gamepad_physics-0.4.2-py3-none-any.whl")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/reports/v0.4.3/packaging_audit.json")
    args = parser.parse_args()
    report = audit(args.wheel, args.previous_wheel)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in (
        "accepted", "actual_package_files", "missing_package_files", "unexpected_package_files")}))
    return int(not report["accepted"])


if __name__ == "__main__":
    raise SystemExit(main())
