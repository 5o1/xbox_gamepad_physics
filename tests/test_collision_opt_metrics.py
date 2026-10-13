"""P1 distance, error-field and coverage primitives."""
import tempfile
import unittest
from pathlib import Path
try:
    import numpy as np
    import trimesh
    from collision_opt.distance import TriangleDistance
    from collision_opt.io import load_hulls
    from collision_opt.metrics import error_field, winding, covered
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, 'collision_opt requires numpy, scipy and trimesh')
class CollisionOptMetricsTests(unittest.TestCase):
    def test_distance_to_triangle_interior_and_edge(self):
        tri = np.array([[[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]]])
        actual, diagnostics = TriangleDistance(tri).query(np.array([[.2,.2,2.],[2.,0.,0.]]))
        np.testing.assert_allclose(actual,[2.,1.])
        self.assertEqual(diagnostics['triangle_count'],1)

    def test_obj_preserves_object_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'two.obj'
            path.write_text('o hull_0\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\no hull_1\nv 0 0 1\nv 1 0 1\nv 0 1 1\nf 4 5 6\n')
            hulls = load_hulls(path)
            self.assertEqual([n for n,_ in hulls],['hull_0','hull_1'])
            self.assertEqual(len(hulls[1][1].vertices),3)
            np.testing.assert_allclose(hulls[1][1].vertices[:,2],1.)

    def test_shifted_cube_outward_and_uncovered_surface(self):
        source = trimesh.creation.box(extents=[.01]*3)
        shifted = source.copy()
        shifted.apply_translation([.001,0,0])
        summary, field = error_field(source,[shifted],density=.1)
        self.assertAlmostEqual(summary['outward']['max_mm'],1.,places=9)
        self.assertGreater(summary['source_uncovered_samples'],0)
        self.assertAlmostEqual(summary['inward']['max_mm'],1.,places=9)
        self.assertEqual(field['points'].shape[1],3)
        self.assertEqual(len(field['points']),len(field['labels']))
        self.assertEqual(len(summary['hulls']),1)
        self.assertEqual(summary['hulls'][0]['vertices'],8)

    def test_winding_and_identity_coverage(self):
        box = trimesh.creation.box(extents=[.01]*3)
        np.testing.assert_allclose(winding(np.array([[0.,0.,0.],[.02,0.,0.]]),box.triangles),[1.,0.],atol=1e-12)
        self.assertTrue(covered(box.vertices,[box]).all())
        summary, _ = error_field(box,[box],density=.05)
        self.assertEqual(summary['source_uncovered_samples'],0)
        self.assertLess(summary['outward']['max_mm'],1e-10)


if __name__ == '__main__':
    unittest.main()
