"""K1 checks of the common collision node, built in an isolated directory."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
DEPS = ("numpy", "trimesh", "scipy")
MISSING = [name for name in DEPS if importlib.util.find_spec(name) is None]


@unittest.skipIf(bool(MISSING), "common collision build requires missing dependencies: " + ", ".join(MISSING))
class CommonCollisionAssetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from build_common_collision import build
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.output = Path(cls.temporary.name)
        cls.manifest = build(cls.output)

    def test_components_shells_convexity_coverage_and_sdf_identity(self):
        import numpy as np
        import trimesh
        from scipy.spatial import ConvexHull
        from build_common_collision import MESHBASE, read_obj, face_shells
        meshes = json.loads((MESHBASE / "manifest.json").read_text())["meshes"]
        self.assertEqual(set(self.manifest["components"]), set(meshes))
        self.assertEqual(len(meshes), 17)
        for component, relative in meshes.items():
            with self.subTest(component=component):
                path = MESHBASE / relative
                vertices, faces = read_obj(path)
                shells = face_shells(faces)
                record = self.manifest["components"][component]
                self.assertEqual(record["shell_count"], len(shells))
                self.assertEqual(len(record["sdf"]), len(shells))
                # Split by OBJ objects, independently of mesh connectivity.
                hulls, hull_vertices, hull_faces, offset = [], [], [], 0
                for line in (self.output / record["coacd"][0]).read_text().splitlines():
                    fields = line.split()
                    if fields[0] == "o":
                        if hull_vertices:
                            hulls.append(trimesh.Trimesh(hull_vertices, hull_faces, process=False))
                            offset += len(hull_vertices)
                        hull_vertices, hull_faces = [], []
                    elif fields[0] == "v":
                        hull_vertices.append([float(x) for x in fields[1:]])
                    elif fields[0] == "f":
                        hull_faces.append([int(x)-1-offset for x in fields[1:]])
                hulls.append(trimesh.Trimesh(hull_vertices, hull_faces, process=False))
                self.assertEqual(len(hulls), record["hull_count"])
                covered = np.zeros(len(vertices), dtype=bool)
                for hull in hulls:
                    convex = ConvexHull(hull.vertices)
                    self.assertLessEqual(abs(convex.volume - hull.volume) / convex.volume, 1e-6)
                    covered |= np.all(vertices @ convex.equations[:, :3].T + convex.equations[:, 3] <= 1e-5, axis=1)
                self.assertTrue(covered.all(), f"{component}: {np.count_nonzero(~covered)} meshbase vertices outside hulls at 10 µm")
                for k, indices in enumerate(shells):
                    sdf = self.output / record["sdf"][k]
                    v, f = read_obj(sdf)
                    self.assertTrue(trimesh.Trimesh(v, f, process=False).is_watertight)
                    used, inverse = np.unique(faces[indices], return_inverse=True)
                    self.assertEqual(v.tobytes(), vertices[used].tobytes())
                    self.assertEqual(f.tobytes(), inverse.reshape(-1, 3).astype(np.int32).tobytes())
                    if len(shells) == 1:
                        self.assertEqual(sdf.read_bytes(), path.read_bytes())
                    else:
                        # Original vertex text is retained; faces only get local indices.
                        lines = path.read_text().splitlines(keepends=True)
                        original_vertices = [line for line in lines if line.startswith("v ")]
                        remap = {int(old): new+1 for new, old in enumerate(used)}
                        expected = "".join(original_vertices[i] for i in used) + "".join(
                            "f " + " ".join(str(remap[int(i)]) for i in row) + "\n" for row in faces[indices])
                        self.assertEqual(sdf.read_bytes(), expected.encode())


if __name__ == "__main__":
    unittest.main()
