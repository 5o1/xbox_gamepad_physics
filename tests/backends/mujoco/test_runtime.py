"""Runtime boundaries on small synthetic fixtures, independent of asset geometry.

All fixture inertias, masses and gains are numerical test definitions rather
than adopted Xbox physical parameters. Full asset acceptance runs separately.
"""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import numpy as np

try:
    import mujoco as mj
except ImportError:
    mj = None

from xbox_gamepad_physics.backends.common.handle import ResetRequest
from xbox_gamepad_physics.backends.common.model import Pose
from xbox_gamepad_physics.errors import AssetImportError
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.state import GamepadState, XBOX_ONE_S_CHANNELS
from xbox_gamepad_physics.mujoco import make_spec, load_standalone, attach_to_spec

ROOT = Path(__file__).resolve().parents[3]
MOTION = ROOT / 'build/resources/common/xbox_one_s/motion/full_controls.json'


@unittest.skipUnless(mj is not None and MOTION.is_file(), 'MuJoCo 3.16.0 and common motion build required')
class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        common = self.root / 'common/xbox_one_s/motion'
        common.mkdir(parents=True)
        shutil.copy2(MOTION, common / 'full_controls.json')
        self.motion = motion_from_dict(json.loads(MOTION.read_text()))
        artifact = self.root / 'mujoco/full_controls'
        artifact.mkdir(parents=True)
        xml = '<mujoco><compiler angle="radian"/><worldbody><body name="controller_body"><inertial mass=".1" pos="0 0 0" diaginertia=".001 .001 .001"/>'
        for joint in self.motion.joints:
            axis = ' '.join(str(v) for v in joint.axis)
            kind = 'hinge' if joint.kind == 'revolute' else 'slide'
            xml += f'<body name="{joint.child}"><joint name="{joint.name}" type="{kind}" axis="{axis}" limited="true" range="{joint.lower} {joint.upper}"/><inertial mass=".01" pos="0 0 0" diaginertia=".0001 .0001 .0001"/><geom name="geom_{joint.name}" type="sphere" size=".001" contype="2" conaffinity="4" group="3"/></body>'
        xml += '</body></worldbody><actuator>'
        for joint in self.motion.joints:
            xml += f'<position name="return_{joint.name}" joint="{joint.name}" kp="1" kv=".01"/>'
        xml += '</actuator></mujoco>'
        (artifact/'xbox_one_s.xml').write_text(xml)
        manifest = {'profile':'full_controls','entrypoint':'xbox_one_s.xml',
            'motion_contract':'common/xbox_one_s/motion/full_controls.json',
            'bindings':{'joints':{j.name:j.name for j in self.motion.joints},
                'actuators':{j.name:'return_'+j.name for j in self.motion.joints},
                'bodies':{'controller_body':'controller_body',**{j.child:j.child for j in self.motion.joints}},
                'root_body':'controller_body','root_joint':'root_free'},
            'neutral_targets':{j.name:0.0 for j in self.motion.joints},
            'initial_positions':{j.name:0.0 for j in self.motion.joints}}
        (artifact/'manifest.json').write_text(json.dumps(manifest))

    def test_compile_bind_and_reset_use_every_common_initial_position(self):
        path = self.root / 'mujoco/full_controls/manifest.json'
        manifest = json.loads(path.read_text())
        # Nonzero values distinguish initialization from the native zero default.
        expected = {j.name: j.lower + .35 * (j.upper - j.lower) for j in self.motion.joints}
        manifest['initial_positions'] = expected
        path.write_text(json.dumps(manifest))
        asset = make_spec(resource_root=self.root)
        model = asset.spec.compile()
        data = mj.MjData(model)
        handle = asset.bind(model, data)
        self.assertEqual(handle.joint_positions(), expected)
        handle.set_joint_positions({name: 0.0 for name in expected})
        handle.reset(ResetRequest())
        self.assertEqual(handle.joint_positions(), expected)
        scene = load_standalone(resource_root=self.root)
        self.assertEqual(scene.gamepad.joint_positions(), expected)

    def test_fixed_free_and_reset(self):
        for fixed in (True, False):
            scene = load_standalone(resource_root=self.root, fixed_root=fixed)
            self.assertEqual(scene.gamepad.root_fixed, fixed)
            self.assertEqual(scene.model.opt.timestep, .0005)
            self.assertEqual(len(scene.gamepad.joint_names), 20)
            for _ in range(10):
                mj.mj_step(scene.model, scene.data)
            self.assertTrue(np.all(np.isfinite(scene.data.qpos)))
            if not fixed:
                pose = Pose((.1,.2,.3))
                scene.gamepad.reset(ResetRequest(root_pose=pose,root_twist=((1,2,3),(4,5,6))))
                np.testing.assert_allclose(scene.gamepad.root_pose().position_m, pose.position_m)
                np.testing.assert_allclose(scene.gamepad.root_twist(), ((1,2,3),(4,5,6)), atol=1e-12)
            else:
                with self.assertRaises(ValueError):
                    scene.gamepad.reset(ResetRequest(root_pose=Pose()))

    def test_signal_roundtrip_pair_and_real_targets(self):
        scene = load_standalone(resource_root=self.root)
        handle = scene.gamepad
        for channel in XBOX_ONE_S_CHANNELS:
            for value in ((-1.,1.) if channel.endswith(('_x','_y')) else (1.,)):
                state = GamepadState.xbox_one_s({channel:value})
                handle.set_gamepad_state(state)
                expected = self.motion.signal_controller.encode(self.motion.signal_controller.decode_joint_targets(state))
                np.testing.assert_allclose(handle.gamepad_state().values, expected.values, atol=1e-12)
        handle.set_physical_events({'pair_bind_connect':1.0})
        self.assertAlmostEqual(handle.physical_events()['pair_bind_connect'],1.0)
        handle.set_gamepad_state(GamepadState.xbox_one_s({}))
        before = scene.data.qpos.copy()
        state = GamepadState.xbox_one_s({'south':1.0})
        handle.set_gamepad_targets(state)
        np.testing.assert_array_equal(scene.data.qpos,before)
        target = self.motion.signal_controller.decode_joint_targets(state)
        for name,value in target.items():
            self.assertEqual(float(scene.data.actuator('return_'+name).ctrl[0]),value)
        for _ in range(10):
            mj.mj_step(scene.model,scene.data)
        self.assertGreater(np.max(np.abs(scene.data.qpos-before)),0)
        handle.restore_passive_targets()
        np.testing.assert_array_equal(scene.data.ctrl,0)

    def test_caller_options_trajectory_names_and_collision_diagnostics(self):
        parent = mj.MjSpec.from_string('<mujoco><option timestep=".003" gravity="0 0 -3"/><worldbody><body name="caller" pos="5 0 1"><freejoint name="caller_free"/><geom name="caller_geom" type="sphere" size=".1" contype="8" conaffinity="16"/></body></worldbody></mujoco>')
        baseline = parent.compile()
        baseline_data = mj.MjData(baseline)
        first = attach_to_spec(parent,resource_root=self.root,prefix='one_',pose=[0,0,0,1,0,0,0])
        second = attach_to_spec(parent,resource_root=self.root,prefix='two_',pose=[1,0,0,1,0,0,0])
        model = parent.compile()
        data = mj.MjData(model)
        handle = first.bind(model,data,expected_external_masks={'caller_geom':True})
        other = second.bind(model,data)
        self.assertEqual(model.opt.timestep,.003)
        stability = next(f for f in handle.findings if f.code == 'numerical_stability_timestep')
        self.assertEqual(stability.context['max_physics_timestep_s'], .0005)
        self.assertEqual(stability.severity, 'warning')
        np.testing.assert_array_equal(model.opt.gravity,[0,0,-3])
        np.testing.assert_array_equal(model.geom('caller_geom').contype,[8])
        np.testing.assert_array_equal(model.geom('caller_geom').solref, baseline.geom('caller_geom').solref)
        np.testing.assert_array_equal(model.geom('caller_geom').solmix, baseline.geom('caller_geom').solmix)
        np.testing.assert_array_equal(model.geom('caller_geom').friction, baseline.geom('caller_geom').friction)
        self.assertTrue(any(f.code=='caller_collision_policy_conflict' for f in handle.findings))
        self.assertEqual(handle.joint_bindings[next(iter(handle.joint_names))], 'one_'+handle.joint_names[0])
        handle.set_joint_target(handle.joint_names[0],.1)
        self.assertEqual(float(data.actuator(other.actuator_names[other.joint_names[0]]).ctrl[0]),0)
        for _ in range(20):
            mj.mj_step(model,data)
            mj.mj_step(baseline,baseline_data)
        np.testing.assert_allclose(data.joint('caller_free').qpos,baseline_data.joint('caller_free').qpos,atol=1e-12)
        with self.assertRaises(AssetImportError):
            attach_to_spec(parent,resource_root=self.root,prefix='one_')

    def test_binding_missing_name_and_nonworld_free_rejected(self):
        asset = make_spec(resource_root=self.root)
        wrong = mj.MjSpec.from_string('<mujoco/>').compile()
        with self.assertRaises(AssetImportError):
            asset.bind(wrong,mj.MjData(wrong))
        parent = mj.MjSpec()
        frame = parent.worldbody.add_frame()
        with self.assertRaises(ValueError):
            attach_to_spec(parent,resource_root=self.root,fixed_root=False,frame=frame)


if __name__ == '__main__':
    unittest.main()
