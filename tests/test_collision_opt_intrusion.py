import unittest
try:
    import numpy as np
    import trimesh
    from collision_opt.intrusion import check_pair
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, 'collision_opt intrusion requires scipy, trimesh and manifold3d')
class IntrusionTests(unittest.TestCase):
    def test_overlap_and_depth_witness(self):
        hull = trimesh.creation.box(extents=[2., 2., 2.])
        space = trimesh.creation.box(extents=[2., 2., 2.])
        space.apply_translation([1.5, 0., 0.])
        result = check_pair(hull, space)
        self.assertTrue(result['intrudes'])
        self.assertAlmostEqual(result['volume_mm3'], 2., places=7)
        self.assertAlmostEqual(result['max_depth_mm'], .5, places=7)
        self.assertEqual(len(result['witness_mm']), 3)

    def test_containment_disconnected_and_touch(self):
        hull = trimesh.creation.box(extents=[2., 2., 2.])
        small = trimesh.creation.box(extents=[.2]*3)
        small.apply_translation([.5, 0., 0.])
        other = small.copy()
        other.apply_translation([-1., 0., 0.])
        space = trimesh.util.concatenate([small, other])
        result = check_pair(hull, space)
        self.assertAlmostEqual(result['max_depth_mm'], .6, places=7)
        touch = hull.copy()
        touch.apply_translation([2., 0., 0.])
        self.assertFalse(check_pair(hull, touch)['intrudes'])

    def test_numerical_tolerance(self):
        hull = trimesh.creation.box(extents=[2.]*3)
        space = hull.copy()
        space.apply_translation([1.995, 0., 0.])
        result = check_pair(hull, space, tolerance_mm=.01)
        self.assertFalse(result['intrudes'])
        self.assertTrue(result['numerical_sliver'])
        self.assertGreater(result['volume_mm3'], 0.)
