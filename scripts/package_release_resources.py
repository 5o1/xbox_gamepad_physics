"""Build a local release zip, integrity sums and the wheel's download lock.

This command creates reviewable artifacts only; it never publishes a release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from build_resources import ROOT, build
from xbox_gamepad_physics.resources import package_version, release_url


def package(output: Path = ROOT / "dist") -> Path:
    resources = ROOT / "build/resources"
    build(output=resources, force=True)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"xbox_gamepad_physics-resources-{package_version()}.zip"
    temporary = archive.with_suffix(".zip.tmp")
    files = [(p, p.relative_to(resources).as_posix()) for p in resources.rglob("*")
             if p.is_file() and ".stamps" not in p.relative_to(resources).parts and p.name != ".release.json"]
    asset_root = ROOT / "assets/xbox_one_s"
    for name in ("source", "visual", "collision_meshbase"):
        files.extend((p, p.relative_to(ROOT).as_posix()) for p in (asset_root / name).rglob("*") if p.is_file())
    # Include all adjacent readmes, licenses and attribution records unchanged.
    for p in asset_root.iterdir():
        if p.is_file() and any(word in p.name.upper() for word in ("README", "LICENSE", "NOTICE", "ATTRIB", "COPYING")):
            files.append((p, p.relative_to(ROOT).as_posix()))
    files.append((ROOT / "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"))
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path, name in sorted(files, key=lambda item: item[1]):
            zipped.write(path, name)
    temporary.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    lock = json.dumps({"version": package_version(), "url": release_url(), "sha256": digest}, indent=2) + "\n"
    for path in (output / "_resource_lock.json", ROOT / "src/xbox_gamepad_physics/_resource_lock.json"):
        temporary_lock = path.with_suffix(".json.tmp")
        temporary_lock.write_text(lock, encoding="utf-8")
        temporary_lock.replace(path)
    print(f"release zip: {archive}")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    package(args.output.resolve())


if __name__ == "__main__":
    main()
