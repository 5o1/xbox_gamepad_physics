"""Deterministic entry-point guidance on generated resource artifacts."""
from pathlib import Path
import json
from xbox_gamepad_physics.backends.registry import ROBOTWIN, UsageSpec


WARNING = ROBOTWIN.usage.warning
EXAMPLE = ROBOTWIN.usage.example
USAGE = ROBOTWIN.usage.manifest()
README = (
    "# Generated gamepad resources\n\n" + WARNING + "\n\n"
    "Use the public loader in your existing SAPIEN scene:\n\n```python\n" + EXAMPLE + "```\n\n"
    "Run `xbox-gamepad-physics guide` for environment, installation, interaction and "
    "rendering instructions. Export a complete example with "
    "`xbox-gamepad-physics example export ./gamepad_example`.\n\n"
    "Use a static box for SDF support; `scene.add_ground` planes do not support SDF "
    "contacts. Loading preserves caller-owned rendering settings. Ray tracing for "
    "review reproduction is optional.\n"
)


def write_resource_readme(directory, usages: tuple[UsageSpec, ...] | None = None):
    """Write guidance without incorporating it into build inputs."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    text = README if usages is None else "# Generated gamepad resources\n\n" + "\n".join(
        item.warning + "\n\n```python\n" + item.example + "```\n\n" + item.guide_command + "\n"
        for item in usages)
    (directory / "README.md").write_text(text, encoding="utf-8")


def document_outputs(directory, usage: UsageSpec | None = None):
    """Annotate generated manifests, URDF headers and artifact directories."""
    directory = Path(directory)
    selected = ROBOTWIN.usage if usage is None else usage
    write_resource_readme(directory, None if usage is None or usage == ROBOTWIN.usage else (usage,))
    for path in sorted(directory.rglob("manifest.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        record["usage"] = USAGE if usage is None else usage.manifest()
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for path in sorted(directory.rglob("mobility.urdf")):
        text = path.read_text(encoding="utf-8")
        comment = "<!--\n" + selected.warning + "\n" + selected.example + (
            "See xbox-gamepad-physics guide and "
            "xbox-gamepad-physics example export ./gamepad_example.\n-->\n"
        )
        if comment not in text:
            declaration, newline, body = text.partition("\n")
            text = declaration + newline + comment + body if declaration.startswith("<?xml") else comment + text
            path.write_text(text, encoding="utf-8")
    for path in sorted(directory.rglob("*")):
        if path.is_dir() and (
            path.name in ("visual", "collision", "sdf", "coacd", "textures")
            or any(child.suffix in (".obj", ".gltf", ".glb", ".urdf") for child in path.iterdir() if child.is_file())
        ):
            write_resource_readme(path, None if selected == ROBOTWIN.usage else (selected,))


def document_dependency(directory: Path, guidance: str) -> None:
    """Annotate one backend's generated documentation without changing physics."""
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    record.setdefault("usage", {})["dependency_installation"] = guidance
    manifest_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    readme = directory / "README.md"
    text = readme.read_text(encoding="utf-8")
    if guidance not in text:
        readme.write_text(text + "\n## Dependency installation\n\n" + guidance + "\n", encoding="utf-8")
