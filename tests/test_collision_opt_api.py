import tempfile
import unittest
from pathlib import Path
try:
    import trimesh
    from collision_opt.api import read_candidates, decide, evaluate, fields_for, sources_for
    HAS_DEPS=True
except ImportError:
    HAS_DEPS=False


@unittest.skipUnless(HAS_DEPS,'collision_opt API requires numpy, scipy and trimesh')
class AcceptanceTests(unittest.TestCase):
    def test_evaluate_returns_metrics_inventory_and_failed_intrusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'sources';candidate=root/'candidate'
            source.mkdir();candidate.mkdir()
            shell=trimesh.creation.box(extents=[.01]*3)
            guide=trimesh.creation.box(extents=[.002]*3);guide.apply_translation([.02,0,0])
            for name,mesh in [('shell',shell),('guide',guide)]:
                mesh.export(source/f'{name}.obj');mesh.export(candidate/f'{name}.obj')
            cfg=dict(inputs=dict(meshbase=str(source)),error_field=dict(
                density_points_per_mm2=.01,source_seed=1,hull_seed=2,coverage_tolerance_mm=.01,
                winding_inside_threshold=.5,hotspot_threshold_mm=.3,
                distribution_bins_mm=[0,.3,1.],comparison_tolerance_mm=1e-6),
                reproduction=dict(reporting_decimals=2,expected_max_mm=0.,expected_p95_mm=0.),
                protection=dict(numerical_tolerance_mm=.01),
                intrusion=dict(minimum_volume_mm3=1e-6,lp_tolerance_mm=1e-7),
                symmetry=dict(exact_threshold_mm=.001,approximate_threshold_mm=.5,
                              density_points_per_mm2=.01,seed=3),
                cooking=dict(vertex_limit=255),openings=dict(hotspot_threshold_mm=.3,
                    xy_margin_mm=3.,minimum_z_mm=12.),baseline_control=dict(shell_components=['shell']))
            originals=read_candidates(candidate,['shell','guide'])
            baseline,_=fields_for(originals,sources_for(cfg),cfg)
            space=trimesh.creation.box(extents=[2.]*3)
            evidence=dict(matched_input=True,hulls=[dict(component=r['component'],
                hull_index=0,shape_index=0,cooked_vertices=8) for r in originals])
            result=evaluate(candidate,cfg,baseline=baseline,spaces={'guide:combined':space},
                protection_metadata=dict(gate_passed=True,positive_control_passed=True,
                                         reproduction_passed=True,controls=[dict(control='guide',
                                             approach=dict(direction_outward=[0.,0.,1.]))]),cooking=evidence)
            self.assertEqual(result['schema_version'],1)
            self.assertEqual(len(result['hulls']),2)
            self.assertEqual(set(result['components']),{'shell','guide'})
            self.assertTrue(result['constraints']['accuracy'])
            self.assertFalse(result['constraints']['protection'])
            self.assertFalse(result['passed'])
            self.assertTrue(result['hulls'][0]['intrusion_checked'])
            self.assertFalse(result['hulls'][1]['intrusion_checked'])

    def test_directory_and_list_preserve_link_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'shell.obj'
            trimesh.creation.box().export(path)
            directory=read_candidates(tmp,['shell'])
            listed=read_candidates([path],['shell'])
            self.assertEqual(directory[0]['link'],'controller_body')
            self.assertEqual(directory[0]['shape_index'],listed[0]['shape_index'])
            with self.assertRaises(ValueError):read_candidates([path],['shell','a'])

    def test_constraints_and_missing_cooking_fail_closed(self):
        value=dict(outward=dict(max_mm=1.,p95_mm=.5),source_uncovered_samples=0,hulls=[dict(vertices=8)])
        metrics={'shell':value}
        baseline={'shell':value}
        cooking=dict(matched_input=True,hulls=[dict(cooked_vertices=8)])
        result=decide(metrics,baseline,[],True,True,cooking)
        self.assertTrue(result['passed'])
        self.assertEqual(result['verdict'],'pass')
        self.assertEqual(result['coverage_claim'],'sampled containment only')
        self.assertFalse(decide(metrics,baseline,[dict(intrudes=True)],True,True,cooking)['passed'])
        self.assertFalse(decide(metrics,baseline,[],True,True,None)['passed'])
        self.assertFalse(decide(metrics,baseline,[],False,True,cooking)['passed'])
        self.assertFalse(decide(metrics,baseline,[],True,False,cooking)['passed'])
        degraded={'shell':dict(value,outward=dict(max_mm=1.1,p95_mm=.5))}
        self.assertFalse(decide(degraded,baseline,[],True,True,cooking)['constraints']['accuracy'])
        shrunk={'shell':dict(value,source_uncovered_samples=1)}
        self.assertFalse(decide(shrunk,baseline,[],True,True,cooking)['constraints']['coverage_sampled'])
