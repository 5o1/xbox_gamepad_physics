import unittest
try:
    import numpy as np
    import trimesh
    from collision_opt.protection import approach, sweep, chain_transform, vertical_roof, cap_gap
    from collision_opt.baseline_control import solid,mesh_of
    from collision_opt.metrics import winding
    HAS_DEPS=True
except ImportError:
    HAS_DEPS=False


@unittest.skipUnless(HAS_DEPS,'protection requires manifold3d, numpy and trimesh')
class ProtectionTests(unittest.TestCase):
    def settings(self):
        return dict(top_normal_max_angle_deg=45,cross_section_inset_mm=.3,
            approach_length_mm=3.,near_top_depth_mm=.5,
            sweep_rotation_step_deg=4.,radial_azimuth_step_deg=30.,
            cap_underside_max_angle_deg=45.,minimum_volume_mm3=1e-6)

    def test_external_direction_does_not_select_buried_face(self):
        body=solid(trimesh.creation.box(extents=[8.]*3))
        control=trimesh.creation.box(extents=[2.]*3);control.apply_translation([0.,4.,0.])
        outward,near,info=approach(control,[0.,1.,0.],self.settings(),body)
        inward,_,wrong=approach(control,[0.,-1.,0.],self.settings(),body)
        self.assertGreater(outward.volume(),0.)
        self.assertEqual(inward.volume(),0.)
        self.assertEqual(wrong['selected_top_faces'],0)
        self.assertAlmostEqual((near-body).volume()/near.volume(),1.,places=8)

    def test_translation_is_continuous_and_exact(self):
        mesh=trimesh.creation.box(extents=[2.]*3)
        chain=[dict(name='press',type='prismatic',parent='controller_body',child='one',
                    origin=[0.,0.,0.],axis=[0.,0.,-1.],lower=0.,upper=.002)]
        sampled,outer,info=sweep(mesh,chain,{},self.settings())
        self.assertAlmostEqual(outer.volume(),16.,places=7)
        self.assertEqual(info['discretization_error_bound_mm'],0.)
        self.assertAlmostEqual(sampled.volume(),outer.volume(),places=7)

    def test_radial_disk_interiors_are_inside_outer_envelope(self):
        mesh=trimesh.creation.box(extents=[2.]*3);mesh.apply_translation([0,0,4.])
        chain=[dict(name='x',type='revolute',origin=[0.,0.,0.],axis=[0.,1.,0.],lower=-.1,upper=.1),
               dict(name='y',type='revolute',origin=[0.,0.,0.],axis=[1.,0.,0.],lower=-.1,upper=.1)]
        motion=dict(joint_space_constraints=[dict(type='radial',joint_ids=['x','y'],radius=.1)])
        _,outer,info=sweep(mesh,chain,motion,self.settings())
        self.assertGreater(info['poses'],12)
        self.assertGreater(info['discretization_error_bound_mm'],0.)
        for q in [dict(x=.027,y=.013),dict(x=.091,y=-.03)]:
            transformed=mesh.copy();transformed.apply_transform(chain_transform(chain,q))
            self.assertLess((solid(transformed)-outer).volume(),1e-6)

    def test_cap_gap_excludes_stem_and_space_below_body(self):
        body=solid(trimesh.creation.box(extents=[4.,4.,2.]))
        stem=trimesh.creation.cylinder(radius=.3,height=3.,sections=16)
        stem.apply_translation([0,0,1.5])
        cap=trimesh.creation.cylinder(radius=1.,height=.5,sections=16)
        cap.apply_translation([0,0,3.25])
        control=solid(trimesh.util.concatenate([stem,cap]))
        roof,footprint=vertical_roof(body)
        gap,_=cap_gap(control,body,roof,footprint,self.settings())
        values=winding(np.array([[.7,0,2.],[0,0,2.],[.7,0,0.]]),mesh_of(gap).triangles)
        self.assertGreater(values[0],.5)
        self.assertLess(values[1],.5)
        self.assertLess(values[2],.5)
