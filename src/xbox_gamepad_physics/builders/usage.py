"""Deterministic entry-point guidance on generated resource artifacts."""
from pathlib import Path
import json


WARNING = (
    "These are internal build artifacts. Direct mesh or URDF loading loses "
    "appearance materials, SDF configuration and signal mapping."
)
EXAMPLE = """import sapien
from xbox_gamepad_physics.robotwin import load_into_scene
pad = load_into_scene(scene, sapien.Pose([0, 0, 0.4]), fixed_root=True)
state = pad.gamepad_state()  # Adapt signals by channel name.
"""
USAGE = {
    "warning": WARNING,
    "entrypoint": "xbox_gamepad_physics.robotwin.load_into_scene",
    "example": EXAMPLE,
    "guide": "xbox-gamepad-physics guide",
    "example_export": "xbox-gamepad-physics example export ./gamepad_example",
}
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


def write_resource_readme(directory):
    """Write guidance without incorporating it into build inputs."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "README.md").write_text(README, encoding="utf-8")


def document_outputs(directory):
    """Annotate generated manifests, URDF headers and artifact directories."""
    directory = Path(directory)
    write_resource_readme(directory)
    for path in sorted(directory.rglob("manifest.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        record["usage"] = USAGE
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for path in sorted(directory.rglob("mobility.urdf")):
        text = path.read_text(encoding="utf-8")
        comment = "<!--\n" + WARNING + "\n" + EXAMPLE + (
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
            write_resource_readme(path)
