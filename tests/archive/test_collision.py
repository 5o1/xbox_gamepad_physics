"""Synthetic geometry tests; these are NOT Xbox physical measurements."""

import importlib.util
from pathlib import Path
import unittest

try:
    import numpy as np
    import trimesh
    from scipy.spatial import QhullError
except ImportError:
    np = None


@unittest.skipIf(
    np is None,
    "NumPy, SciPy and Trimesh required; run on GPU-node existing environment",
)
class CollisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2] / "scripts/archive/build_button_colliders.py"
        spec = importlib.util.spec_from_file_location("colliders", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_cube_hull_preserves_surface(self):
        cube = trimesh.creation.box()
        hull, outside, tolerance = self.module.convex_candidate(cube)
        self.assertTrue(hull.is_watertight)
        self.assertLessEqual(outside, tolerance)
        self.assertLess(self.module.sampled_distances(cube, hull)["max_native"], 1e-12)

    def test_missing_face_is_detected_as_new_surface(self):
        cube = trimesh.creation.box()
        # Remove both triangles on one face: convexification must not look lossless.
        cube.update_faces(cube.face_normals[:, 0] < 0.5)
        hull, _, _ = self.module.convex_candidate(cube)
        self.assertGreater(self.module.sampled_distances(hull, cube)["max_native"], 0.1)

    def test_flat_geometry_is_not_silently_thickened(self):
        mesh = trimesh.Trimesh(
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
            faces=[[0, 1, 2]],
            process=False,
        )
        with self.assertRaises(QhullError):
            self.module.convex_candidate(mesh)

    def test_distance_witness_reproduces_reported_maximum(self):
        cube = trimesh.creation.box()
        other = cube.copy()
        other.apply_translation([3, 0, 0])
        result = self.module.sampled_distances(cube, other)
        witness = result["max_witness"]
        distance = np.linalg.norm(
            np.array(witness["point_native"]) - witness["closest_point_native"]
        )
        self.assertAlmostEqual(distance, result["max_native"])
        self.assertAlmostEqual(distance, 3.0)


if __name__ == "__main__":
    unittest.main()
