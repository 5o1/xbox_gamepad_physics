import importlib.util
from pathlib import Path
import unittest

try:
    import numpy as np
    import trimesh
    if importlib.util.find_spec("scipy") is None:
        raise ImportError("SciPy required for fitting")
except ImportError:
    np = None


@unittest.skipIf(np is None, "Run geometry tests in existing GPU-node environment")
class SphereFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2] / "scripts/archive/fit_stick_geometry.py"
        spec = importlib.util.spec_from_file_location("fit", path)
        cls.fit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.fit)

    def test_known_sphere(self):
        points = np.array(
            [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]
        ) * 0.012 + [0.03, -0.02, 0.04]
        result = self.fit.fit_sphere(points, points)
        np.testing.assert_allclose(
            result["candidate_center_m"], [0.03, -0.02, 0.04], atol=1e-12
        )
        self.assertAlmostEqual(result["candidate_radius_m"], 0.012)
        self.assertIsNone(result["mechanical_pivot"])

    def test_plane_rejected(self):
        with self.assertRaises(ValueError):
            self.fit.fit_sphere(
                [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], [[0, 0, 0]]
            )

    def test_nonspherical_surface_reports_error(self):
        mesh = trimesh.creation.icosphere(subdivisions=2)
        mesh.apply_scale([1, 2, 3])
        result = self.fit.fit_sphere(mesh.vertices, mesh.triangles_center)
        self.assertGreater(result["vertex_relative_rms"], 0.1)


if __name__ == "__main__":
    unittest.main()
