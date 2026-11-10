"""Release default propagation and exact native-capability boundaries."""
import json
from pathlib import Path
import unittest

from xbox_gamepad_physics.robotwin.physical import (
    configure_robotwin_dynamics, require_native_cone_engine,
    NATIVE_D6_SAPIEN_VERSION, NATIVE_D6_COMPATIBLE_VERSIONS,
)

ROOT = Path(__file__).resolve().parents[2]

def load(path):
    return json.loads(path.read_text())

class RoboTwinDefaultsTest(unittest.TestCase):
    def test_geometry_audit_ignores_only_usage_comments(self):
        from tests.acceptance.robotwin.review_public_resource_delivery import same_physics_input
        a=b'<robot><!-- old usage --><link name="body"><inertial><mass value="1"/></inertial></link></robot>'
        self.assertTrue(same_physics_input('mobility.urdf',a,a.replace(b'old usage',b'new usage')))
        self.assertFalse(same_physics_input('mobility.urdf',a,a.replace(b'value="1"',b'value="2"')))

    def test_public_and_packaged_default_evidence(self):
        for name in ('full_controls.json', 'robotwin_v042_policy.json'):
            self.assertEqual(load(ROOT/'references'/name), load(ROOT/'src/xbox_gamepad_physics/build_data/references'/name))
        self.assertEqual(load(ROOT/'references/catalog.json')['sources']['robotwin_v042_policy'],
                         load(ROOT/'src/xbox_gamepad_physics/build_data/references/catalog.json')['sources']['robotwin_v042_policy'])
        options=load(ROOT/'references/full_controls.json')['backend_options']['robotwin']
        self.assertEqual(options['shaft_tilt_limit']['mechanism'],'native_d6_cone')
        self.assertEqual(options['joint_friction_viscous_mapping'],'drive_damping')
        self.assertEqual(options['stick_click_preload']['drive_target_m'],0)
        points=options['solver_iterations']['validated_points']
        self.assertEqual([[p[k]['value'] for k in ('timestep_s','position','velocity')] for p in points],
                         [[.001,10,1],[.004,64,16]])
        for record in options['joint_friction_params'].values():
            self.assertEqual([record[k]['value'] for k in ('static_effort','dynamic_effort','viscous')],[0,0,.0018707873827064705])
        source=points[1]['position']['evidence'][0]
        self.assertIn('View',source['locator'])
        self.assertIn('official3.0.3',source['derivation'])
        self.assertIn('idle-only',source['derivation'])
        self.assertIn('A-10-1',points[0]['position']['evidence'][0]['locator'])
        policy=load(ROOT/'references/robotwin_v042_policy.json')
        self.assertEqual(policy['solver_policy']['solver_iterations'],options['solver_iterations'])

    def test_default_generator_clears_legacy_without_calibration(self):
        source=load(ROOT/'references/full_controls.json')
        base={'stiffness':1.,'drive_damping':1.,'passive_damping':0.,'effort':1.,'target':0.,'unit':'rad'}
        names=list(source['backend_options']['robotwin']['joint_friction_params'])
        records={n:dict(base) for n in names+['left_stick_click']}
        configure_robotwin_dynamics(records,source,'full_controls')
        self.assertTrue(all(r['friction']==0 for r in records.values()))
        # The old partial profile consumes only its own evidence and legacy path.
        left=load(ROOT/'references/left_stick.json')
        records={n:dict(base) for n in ['left_stick_x','left_stick_y']}
        configure_robotwin_dynamics(records,left,'left_stick')
        self.assertTrue(all(r['friction']==left['passive_dynamics']['joint_friction_nm'] for r in records.values()))

    def test_only_explicit_engine_builds_support_native_cone(self):
        policy={'mechanism':'native_d6_cone'}
        self.assertTrue(NATIVE_D6_SAPIEN_VERSION.endswith('.a3'))
        for version in NATIVE_D6_COMPATIBLE_VERSIONS:
            require_native_cone_engine(policy,version)
        for version in ['3.0.3','3.0.3+concon.physx5.6.1.a1','3.0.3+concon.physx5.6.1.a4']:
            with self.subTest(version=version),self.assertRaises(ValueError):
                require_native_cone_engine(policy,version)
        require_native_cone_engine({'mechanism':'native_distance_upper_bound'},'3.0.3')

if __name__=='__main__':unittest.main()
