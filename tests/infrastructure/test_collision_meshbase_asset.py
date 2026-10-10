"""Properties of the frozen collision mesh base; it is not compared with upstream sources."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets/xbox_one_s/collision_meshbase"
CONTROLS = {
    "a", "b", "x", "y", "guide", "view", "menu", "pair", "dpad",
    "left_stick", "right_stick", "left_shoulder", "right_shoulder",
    "left_trigger", "right_trigger",
}
COMPONENTS = CONTROLS | {"shell", "shell_front_plate"}
TWO_SHELL_COMPONENTS = {"left_stick", "right_stick"}
HAS_NUMPY = importlib.util.find_spec("numpy") is not None


def _read_obj(path: Path) -> tuple[list[list[float]], list[list[int]]]:
    vertices, faces = [], []
    for line in path.read_text().splitlines():
        tokens = line.split()
        if tokens and tokens[0] == "v":
            vertices.append([float(x) for x in tokens[1:4]])
        elif tokens and tokens[0] == "f":
            if len(tokens) != 4:
                raise ValueError(f"{path.name}: expected triangles only")
            faces.append([int(x) - 1 for x in tokens[1:]])
    return vertices, faces


def _connected_link(edges: list[tuple[int, int]]) -> bool:
    """True when a vertex link is one cycle (every vertex of a closed 2-manifold)."""

    graph: dict[int, list[int]] = {}
    for a, b in edges:
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, []).append(a)
    if any(len(neighbours) != 2 for neighbours in graph.values()):
        return False
    seen: set[int] = set()
    stack = [next(iter(graph))]
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(graph[node])
    return len(seen) == len(graph)


class CollisionMeshbaseAssetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ASSET / "manifest.json").read_text(encoding="utf-8"))

    def test_files_components_and_attribution(self):
        manifest = self.manifest
        self.assertEqual(
            set(manifest),
            {"meshes", "derived_from", "license", "author", "source_url",
             "changes", "coordinate_frame", "units", "components"},
        )
        self.assertEqual(set(manifest["meshes"]), COMPONENTS)
        self.assertEqual(set(manifest["components"]), COMPONENTS)
        self.assertEqual(manifest["license"], "CC-BY-4.0")
        self.assertEqual(manifest["author"], "BatonyRobson")
        self.assertTrue(manifest["source_url"].startswith("https://sketchfab.com/3d-models/"))
        self.assertTrue(manifest["changes"].strip())
        self.assertEqual(manifest["units"], "m")
        self.assertIn("Z up", manifest["coordinate_frame"])
        self.assertTrue((ASSET / "README.md").is_file())
        self.assertTrue((ROOT / manifest["derived_from"]["generator"]).is_file())

        on_disk = {path.relative_to(ASSET).as_posix() for path in (ASSET / "meshes").glob("*.obj")}
        self.assertEqual(on_disk, {f"meshes/{name}.obj" for name in COMPONENTS})
        for name, relative in manifest["meshes"].items():
            with self.subTest(component=name):
                self.assertEqual(relative, f"meshes/{name}.obj")
                self.assertTrue(manifest["components"][name])

    @unittest.skipIf(not HAS_NUMPY, "numpy is unavailable; per-shell geometry checks need numpy")
    def test_every_shell_is_closed_manifold_and_outward(self):
        import numpy as np

        for name, relative in self.manifest["meshes"].items():
            with self.subTest(component=name):
                raw_vertices, raw_faces = _read_obj(ASSET / relative)
                vertices = np.array(raw_vertices, float)
                faces = np.array(raw_faces, int)
                self.assertTrue(len(vertices) and len(faces))
                self.assertTrue(np.isfinite(vertices).all())
                self.assertTrue((faces >= 0).all() and (faces < len(vertices)).all())

                edges: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
                links: list[list[tuple[int, int]]] = [[] for _ in vertices]
                for index, face in enumerate(faces.tolist()):
                    self.assertEqual(len(set(face)), 3)
                    for i in range(3):
                        a, b, c = face[i], face[(i + 1) % 3], face[(i + 2) % 3]
                        edges.setdefault(tuple(sorted((a, b))), []).append((index, a, b))
                        links[a].append((b, c))

                adjacency: list[set[int]] = [set() for _ in faces]
                for uses in edges.values():
                    self.assertEqual(len(uses), 2, "open or non-manifold edge")
                    first, second = uses
                    self.assertEqual(first[1:], second[:0:-1], "inconsistent winding")
                    adjacency[first[0]].add(second[0])
                    adjacency[second[0]].add(first[0])
                for link in links:
                    self.assertTrue(link, "unreferenced vertex")
                    self.assertTrue(_connected_link(link), "non-manifold vertex")

                pending = set(range(len(faces)))
                shells = []
                while pending:
                    stack, shell = [min(pending)], []
                    while stack:
                        face = stack.pop()
                        if face in pending:
                            pending.remove(face)
                            shell.append(face)
                            stack.extend(adjacency[face])
                    shells.append(shell)
                for shell in shells:
                    triangles = vertices[faces[shell]]
                    triangles = triangles - triangles.reshape(-1, 3).mean(0)
                    volume = np.einsum(
                        "ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])
                    ).sum() / 6
                    self.assertGreater(volume, 0, "every shell must face outward")
                self.assertEqual(len(shells), 2 if name in TWO_SHELL_COMPONENTS else 1)


if __name__ == "__main__":
    unittest.main()
