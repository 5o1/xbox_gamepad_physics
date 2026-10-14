"""Export the three independent user-facing example files."""
from pathlib import Path
from importlib.resources import files
from xbox_gamepad_physics.errors import ResourceError

def export_example(destination):
    destination = Path(destination).expanduser().resolve()
    names = ("run_robotwin.py", "smoke_full_controls.yaml", "render_review.yaml")
    source = files("xbox_gamepad_physics.examples").joinpath("templates")
    for name in names:
        path = destination / name
        if path.exists() and path.read_bytes() != source.joinpath(name).read_bytes():
            raise ResourceError(f"example export would replace {path}; choose an empty directory")
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        (destination / name).write_bytes(source.joinpath(name).read_bytes())
    (destination / "run_robotwin.py").chmod(0o755)
    return destination
