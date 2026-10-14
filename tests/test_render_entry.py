"""Repository render configuration must go through the shared RoboTwin entry."""
import ast
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
WHITELIST = {
    "scripts/archive/": "Historical standalone probes are retained per the ruling and are no longer current rendering entry points.",
    "scripts/render_robotwin_full_controls_review.py": "Generator for reviewed renders and inspection videos; retained per ruling 5 as provenance for approved results. Migration to the public entry point is scheduled separately.",
    "examples/robotwin_visual.py": "Original standalone example with an approved appearance; the ruling requires existing examples to remain unchanged.",
    "examples/robotwin_left_stick.py": "Existing standalone left-stick interaction example; the ruling requires its own scene configuration to be preserved.",
}
SETTINGS = {"set_camera_shader_dir", "SapienRenderer", "RenderSystem",
            "add_directional_light", "add_point_light", "set_ambient_light", "set_global_config"}


def violations(source, path):
    tree = ast.parse(source)
    aliases = {a.asname or a.name: a.name for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom) for a in n.names}
    permitted = next((n for n in tree.body if path == "src/xbox_gamepad_physics/examples/scene.py"
                      and isinstance(n, ast.FunctionDef) and n.name == "create_render_scene"), None)
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
        name = aliases.get(name, name)
        if name in SETTINGS or name.startswith("set_ray_tracing_"):
            if permitted and permitted.lineno <= node.lineno <= permitted.end_lineno:
                continue
            result.append(f"{path}:{node.lineno}: {name}")
    return result


class RenderEntryTest(unittest.TestCase):
    def test_repository_uses_shared_render_entry(self):
        if not (ROOT / '.git').exists():
            self.skipTest('The runtime image lacks Git metadata; scan tracked files in a local checkout')
        files = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        ).decode().split("\0")
        errors = []
        for name in sorted(set(files)):
            if not name.endswith(".py") or any(name == item or (item.endswith("/") and name.startswith(item)) for item in WHITELIST):
                continue
            errors.extend(violations((ROOT/name).read_text(), name))
        self.assertEqual(errors, [], "Bypasses the public rendering entry point:\n" + "\n".join(errors))

    def test_guard_distinguishes_physics_and_catches_aliases(self):
        self.assertEqual(violations("scene = sapien.Scene()", "probe.py"), [])
        self.assertEqual(len(violations("from sapien import SapienRenderer as R\nx=R()", "bad.py")), 1)
        self.assertEqual(len(violations("scene.add_point_light([],[])", "bad.py")), 1)
        self.assertEqual(violations('def create_render_scene():\n scene.set_ambient_light([])', "src/xbox_gamepad_physics/examples/scene.py"), [])
        self.assertEqual(len(violations('def other():\n scene.set_ambient_light([])', "src/xbox_gamepad_physics/examples/scene.py")), 1)


if __name__ == "__main__":
    unittest.main()
