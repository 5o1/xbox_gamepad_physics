import unittest
try:
    import trimesh
    from collision_opt.symmetry import source_regions, classify
    HAS_DEPS=True
except ImportError:
    HAS_DEPS=False


@unittest.skipUnless(HAS_DEPS, 'collision_opt symmetry requires scipy and trimesh')
class SymmetryTests(unittest.TestCase):
    def test_exact_triangle_region_and_mixed_structure(self):
        mesh=trimesh.creation.icosphere(subdivisions=0, radius=.01)
        settings=dict(exact_threshold_mm=.001, approximate_threshold_mm=.5,
                      density_points_per_mm2=.01, seed=3)
        regions=source_regions({'ball':mesh},settings)
        self.assertTrue((regions['ball']['region']==0).all())
        row=classify([dict(component='ball',hull_index=0,shape_index=0,
                           link='ball',mesh=mesh)],{'ball':mesh},settings)[0]
        self.assertEqual(row['symmetry_region'],'exact')
        self.assertEqual(set(row['symmetry_fractions']),{'exact','approximate','asymmetric'})

    def test_off_centre_is_asymmetric(self):
        mesh=trimesh.creation.box(extents=[.002]*3)
        mesh.apply_translation([.02,0,0])
        regions=source_regions({'one':mesh},dict(exact_threshold_mm=.001,approximate_threshold_mm=.5))
        self.assertTrue((regions['one']['region']==2).all())
