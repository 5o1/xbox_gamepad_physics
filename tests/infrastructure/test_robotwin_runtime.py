from __future__ import annotations

import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from xbox_gamepad_physics.profiles import BackendProfile
from xbox_gamepad_physics.motion import MotionJoint
from xbox_gamepad_physics.errors import ResourceNotFoundError
from xbox_gamepad_physics.controller import (
    AxisSignalMapping,
    GamepadSignalController,
    RadialSignalGroup,
)
from xbox_gamepad_physics.robotwin.articulation import XboxOneSArticulation
from xbox_gamepad_physics.robotwin.errors import (
    JointConfigurationError,
    RoboTwinManifestError,
    SceneCompatibilityError,
)
from xbox_gamepad_physics.robotwin.install import install_native_assets
from xbox_gamepad_physics.robotwin import loader as loader_module


class FakeJoint:
    def __init__(self, name):
        self.name = name
        self.dof = 1
        self.drive_calls = []
        self.friction_calls = []
        self.target_calls = []
        self.limit_calls = []

    def set_limits(self, limits):
        self.limit_calls.append(limits)

    def set_drive_properties(self, stiffness, damping, *, force_limit):
        self.drive_calls.append((stiffness, damping, force_limit))

    def set_friction(self, friction):
        self.friction_calls.append(friction)

    def set_drive_target(self, target):
        self.target_calls.append(target)


class FakeArticulation:
    def __init__(self):
        self.joints = [FakeJoint("button_a"), FakeJoint("left_stick_x")]
        self.qpos = [0.0, 0.0]
        self.qvel = [0.0, 0.0]
        self.root_poses = []
        self.mass_writes = []
        self.links = [FakeLink()]

    def get_active_joints(self):
        return self.joints

    def get_qpos(self):
        return list(self.qpos)

    def set_qpos(self, value):
        self.qpos = list(value)

    def get_qvel(self):
        return list(self.qvel)

    def set_root_pose(self, value):
        self.root_poses.append(value)

    def get_links(self):
        return self.links


class FakeCollisionShape:
    def __init__(self):
        self.materials = []
        self.contact_offsets = []
        self.rest_offsets = []
        self.groups = [2, 3, 4, 5]

    def get_collision_groups(self):
        return list(self.groups)

    def set_collision_groups(self, groups):
        self.groups = list(groups)

    def set_physical_material(self, value):
        self.materials.append(value)

    def set_contact_offset(self, value):
        self.contact_offsets.append(value)

    def set_rest_offset(self, value):
        self.rest_offsets.append(value)


class FakeLink:
    def __init__(self):
        self.shape = FakeCollisionShape()

    def get_collision_shapes(self):
        return [self.shape]


class FakeSetPoseArticulation(FakeArticulation):
    set_root_pose = None

    def set_pose(self, value):
        self.root_poses.append(value)


class FakeLoader:
    def __init__(self, articulation, use_multiple=True):
        self.articulation = articulation
        self.fix_root_link = None
        self.load_multiple_collisions_from_file = None
        self.paths = []
        if not use_multiple:
            self.load_multiple = None

    def load_multiple(self, path):
        self.paths.append(path)
        return ([self.articulation], [])

    def load(self, path):
        self.paths.append(path)
        return self.articulation


class FakeScene:
    def __init__(self, loader):
        self.loader = loader

    def create_urdf_loader(self):
        return self.loader

    def create_physical_material(self, static_friction, dynamic_friction, restitution):
        return (static_friction, dynamic_friction, restitution)


def ready_profile(urdf):
    return BackendProfile(
        schema_version=1,
        asset_id="xbox_one_s",
        backend="robotwin",
        profile="test_ready",
        available=True,
        dynamics_ready=True,
        entrypoint="mobility.urdf",
        required_files=("mobility.urdf",),
        reason=None,
        manifest_path=urdf.parent / "manifest.json",
    )


def ready_manifest():
    return {
        "schema_version": 1,
        "asset_id": "xbox_one_s",
        "backend": "robotwin",
        "profile": "test_ready",
        "available": True,
        "dynamics_ready": True,
        "entrypoint": "mobility.urdf",
        "required_files": ["mobility.urdf"],
        "reason": None,
        "joint_dynamics": [
            {
                "name": "button_a",
                "stiffness": 12.0,
                "damping": 0.4,
                "force_limit": 2.0,
                "friction": 0.1,
                "target": 0.0,
            },
            {
                "name": "left_stick_x",
                "stiffness": 3.0,
                "damping": 0.2,
                "force_limit": 1.0,
                "friction": 0.05,
                "target": 0.0,
            },
        ],
        "state_mapping": {
            "axes": [
                {
                    "channel": "left_x",
                    "joint": "left_stick_x",
                    "lower": -0.4,
                    "upper": 0.4,
                }
            ],
            "radial_groups": [],
        },
        "contact_material": {
            "static_friction": 0.5,
            "dynamic_friction": 0.4,
            "restitution": 0.05,
            "contact_offset_m": 0.0002,
            "rest_offset_m": 0.0,
        },
        "visual_binding": {},
    }


def ready_urdf():
    inertial = """
      <inertial>
        <origin xyz="0 0 0" rpy="0 0 0"/>
        <mass value="0.1"/>
        <inertia ixx="0.001" ixy="0" ixz="0" iyy="0.001" iyz="0" izz="0.001"/>
      </inertial>
    """
    return f"""<robot name="fake_xbox_one_s">
      <link name="shell">
        {inertial}
        <collision><geometry><box size="0.1 0.1 0.02"/></geometry></collision>
      </link>
      <link name="a">{inertial}</link>
      <link name="stick_x">{inertial}</link>
      <joint name="button_a" type="prismatic">
        <parent link="shell"/><child link="a"/>
        <origin xyz="0 0 0" rpy="0 0 0"/><axis xyz="0 0 1"/>
        <limit lower="0" upper="0.001" effort="2" velocity="1"/>
      </joint>
      <joint name="left_stick_x" type="revolute">
        <parent link="shell"/><child link="stick_x"/>
        <origin xyz="0 0 0" rpy="0 0 0"/><axis xyz="1 0 0"/>
        <limit lower="-0.4" upper="0.4" effort="1" velocity="2"/>
      </joint>
    </robot>"""


class RoboTwinRuntimeTest(unittest.TestCase):
    def _load(self, *, use_multiple=True, task_wrapper=False, collision="coacd", version="3.0.3"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        urdf = Path(temporary.name).resolve() / "mobility.urdf"
        urdf.write_text(ready_urdf(), encoding="utf-8")
        articulation = FakeArticulation()
        fake_loader = FakeLoader(articulation, use_multiple=use_multiple)
        scene = FakeScene(fake_loader)
        passed_scene = SimpleNamespace(scene=scene) if task_wrapper else scene
        link_builder = SimpleNamespace(name="shell", collision_records=["original"])
        link_builder.add_nonconvex_collision_from_file = lambda path: link_builder.collision_records.append(path)
        builder = SimpleNamespace(link_builders=[link_builder], build=lambda: articulation)
        fake_loader.parse = lambda path: ([builder], [], [])
        fake_loader.builder = builder
        config = SimpleNamespace(spacing=0.01, subgridSize=6, num_threads_for_construction=4)
        fake_physx = SimpleNamespace(
            get_sdf_config=lambda: config, set_sdf_config=mock.Mock(),
            PhysxCollisionShapeTriangleMesh=type("Triangle", (), {}),
        )
        manifest = ready_manifest()
        manifest["collision_variants"] = {"sdf": {"spacing_m": 0.001, "links": {"shell": ["collision/sdf/shell_0.obj"]}}}
        pose = SimpleNamespace(p=(1, 2, 3), q=(1, 0, 0, 0))

        def fake_resource_path(backend, profile, *parts, must_exist=True):
            self.assertEqual((backend, profile), ("robotwin", "test_ready"))
            self.assertEqual(parts, ("mobility.urdf",))
            return urdf

        with (
            mock.patch.object(loader_module.metadata, "version", return_value=version),
            mock.patch.object(
                loader_module, "require_physics_ready", return_value=ready_profile(urdf)
            ),
            mock.patch.object(
                loader_module, "load_json_resource", return_value=manifest
            ),
            mock.patch.object(loader_module, "resource_path", fake_resource_path),
            mock.patch.object(
                loader_module, "_import_sapien",
                **({"return_value": SimpleNamespace(physx=fake_physx)} if collision in ("sdf", None)
                   else {"side_effect": AssertionError("eager import")})
            ),
            mock.patch(
                "xbox_gamepad_physics.robotwin.visual.attach_visual_to_articulation"
            ),
        ):
            wrapper = loader_module.load_into_scene(
                passed_scene, pose, fixed_root=True, profile="test_ready",
                **({"collision": collision} if collision is not None else {})
            )
        return wrapper, articulation, fake_loader, pose, urdf

    def test_direct_scene_loads_absolute_resource_and_configures_by_name(self):
        wrapper, articulation, fake_loader, pose, urdf = self._load()
        self.assertIsInstance(wrapper, XboxOneSArticulation)
        self.assertEqual(fake_loader.paths, [str(urdf)])
        self.assertTrue(Path(fake_loader.paths[0]).is_absolute())
        self.assertIs(fake_loader.fix_root_link, True)
        self.assertIs(fake_loader.load_multiple_collisions_from_file, True)
        self.assertEqual(articulation.root_poses, [pose])
        self.assertEqual(articulation.joints[0].drive_calls, [(12.0, 0.4, 2.0)])
        self.assertEqual(articulation.joints[1].drive_calls, [(3.0, 0.2, 1.0)])
        self.assertEqual(articulation.joints[0].friction_calls, [0.1])
        self.assertEqual(articulation.joints[0].target_calls, [0.0])
        self.assertEqual(articulation.mass_writes, [])
        self.assertEqual(articulation.links[0].shape.groups, [2, 3, 4 | 0x80000000, 0x5842])

    def test_sdf_replaces_collision_records_and_sets_groups(self):
        _, articulation, loader, _, urdf = self._load(collision="sdf")
        self.assertEqual(loader.paths, [])
        self.assertEqual(loader.builder.link_builders[0].collision_records,
                         [str(urdf.parent / "collision/sdf/shell_0.obj")])
        self.assertEqual(articulation.links[0].shape.groups, [2, 3, 4 | 0x80000000, 0x5842])

    def test_sdf_unsupported_error_is_explicit(self):
        with mock.patch.object(loader_module, "_validated_description"), mock.patch.object(loader_module.metadata, "version", return_value="3.0.3"), mock.patch.object(loader_module, "_import_sapien", return_value=SimpleNamespace(
            physx=SimpleNamespace(PhysxCollisionShapeTriangleMesh=type("Triangle", (), {})))):
            with self.assertRaisesRegex(SceneCompatibilityError, "SAPIEN >= 3.0.3"):
                loader_module.load_into_scene(None, None, True, collision="sdf")

    def test_default_loads_sdf(self):
        _, _, loader, _, urdf = self._load(collision=None)
        self.assertEqual(loader.paths, [])
        self.assertEqual(loader.builder.link_builders[0].collision_records,
                         [str(urdf.parent / "collision/sdf/shell_0.obj")])

    def test_low_version_default_error_has_two_remedies(self):
        with mock.patch.object(loader_module, "_validated_description"), mock.patch.object(loader_module.metadata, "version", return_value="3.0.0b1"), mock.patch.object(loader_module, "_import_sapien", return_value=SimpleNamespace()):
            with self.assertRaisesRegex(SceneCompatibilityError, 'upgrade to SAPIEN 3.0.3 or explicitly pass collision="coacd"'):
                loader_module.load_into_scene(None, None, True)

    def test_explicit_coacd_works_on_both_versions(self):
        for version in ("3.0.0b1", "3.0.3"):
            with self.subTest(version=version):
                _, _, loader, _, urdf = self._load(collision="coacd", version=version)
                self.assertEqual(loader.paths, [str(urdf)])

    def test_invalid_collision_variant(self):
        with self.assertRaisesRegex(ValueError, "collision must be"):
            loader_module.load_into_scene(None, None, True, collision="other")

    def test_common_motion_limits_are_applied_after_urdf_load(self):
        articulation = FakeArticulation()
        dynamics = (
            loader_module.JointDynamics("button_a", 12.0, 0.4, 2.0, 0.1, 0.0),
            loader_module.JointDynamics("left_stick_x", 3.0, 0.2, 1.0, 0.05, 0.0),
        )
        motion = (
            MotionJoint("button_a", "prismatic", "shell", "a", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.0, 0.002, "m"),
            MotionJoint("left_stick_x", "revolute", "shell", "stick_x", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), -0.3, 0.3, "rad"),
        )
        controller = GamepadSignalController.xbox_one_s(
            (AxisSignalMapping("left_x", "left_stick_x", -0.3, 0.3),)
        )
        loader_module._configure_joints(articulation, dynamics, motion, controller)
        self.assertEqual(articulation.joints[0].limit_calls, [[[0.0, 0.002]]])
        self.assertEqual(articulation.joints[1].limit_calls, [[[-0.3, 0.3]]])

    def test_robotwin_task_scene_and_single_load_fallback_are_supported(self):
        wrapper, _, fake_loader, _, _ = self._load(
            use_multiple=False, task_wrapper=True
        )
        self.assertEqual(wrapper.joint_names, ("button_a", "left_stick_x"))
        self.assertEqual(len(fake_loader.paths), 1)

    def test_numeric_pose_contract_uses_metres_and_wxyz(self):
        class Pose:
            def __init__(self, *, p, q):
                self.p = tuple(p)
                self.q = tuple(q)

        with mock.patch.object(
            loader_module, "_import_sapien", return_value=SimpleNamespace(Pose=Pose)
        ):
            pose = loader_module._coerce_pose([0.1, -0.2, 0.8, 2.0, 0.0, 0.0, 0.0])
        self.assertEqual(pose.p, (0.1, -0.2, 0.8))
        self.assertEqual(pose.q, (1.0, 0.0, 0.0, 0.0))
        with self.assertRaisesRegex(SceneCompatibilityError, "must contain"):
            loader_module._coerce_pose([0.0] * 6)

    def test_pinned_robotwin_set_pose_fallback_is_supported(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        urdf = Path(temporary.name).resolve() / "mobility.urdf"
        urdf.write_text(ready_urdf(), encoding="utf-8")
        articulation = FakeSetPoseArticulation()
        scene = FakeScene(FakeLoader(articulation))
        pose = SimpleNamespace(p=(0, 0, 0), q=(1, 0, 0, 0))
        with (
            mock.patch.object(
                loader_module, "require_physics_ready", return_value=ready_profile(urdf)
            ),
            mock.patch.object(
                loader_module, "load_json_resource", return_value=ready_manifest()
            ),
            mock.patch.object(loader_module, "resource_path", return_value=urdf),
            mock.patch(
                "xbox_gamepad_physics.robotwin.visual.attach_visual_to_articulation"
            ),
        ):
            loader_module.load_into_scene(
                scene, pose, fixed_root=True, profile="test_ready", collision="coacd"
            )
        self.assertEqual(articulation.root_poses, [pose])

    def test_wrapper_reads_and_writes_qpos_only_through_joint_names(self):
        wrapper, articulation, _, _, _ = self._load()
        wrapper.set_joint_positions({"left_stick_x": 0.25, "button_a": 0.001})
        self.assertEqual(articulation.qpos, [0.001, 0.25])
        self.assertEqual(wrapper.joint_position("left_stick_x"), 0.25)
        self.assertEqual(
            wrapper.joint_positions(), {"button_a": 0.001, "left_stick_x": 0.25}
        )
        with self.assertRaisesRegex(KeyError, "unknown Xbox One S joint"):
            wrapper.joint_position("joint_0")

    def test_gamepad_state_normalizes_and_projects_stick_radius(self):
        articulation = FakeArticulation()
        articulation.qpos = [0.4, 0.4]
        signal_controller = GamepadSignalController.xbox_one_s(
            [
                AxisSignalMapping("left_x", "button_a", -0.4, 0.4),
                AxisSignalMapping("left_y", "left_stick_x", -0.4, 0.4),
            ],
            [RadialSignalGroup(("left_x", "left_y"), 1.0)],
        )
        wrapper = XboxOneSArticulation(
            articulation,
            ["button_a", "left_stick_x"],
            signal_controller,
        )
        state = wrapper.gamepad_state()
        self.assertAlmostEqual(state.channel("left_x"), 2 ** -0.5)
        self.assertAlmostEqual(state.channel("left_y"), 2 ** -0.5)
        self.assertTrue(state.is_available("left_x"))
        self.assertTrue(state.is_available("left_y"))
        self.assertFalse(state.is_available("right_x"))
        self.assertEqual(sum(state.available_mask), 2)

        task_state = wrapper.gamepad_state(task_channels=("left_x",))
        self.assertEqual(sum(task_state.task_mask), 1)
        self.assertTrue(task_state.is_task_channel("left_x"))
        self.assertFalse(task_state.is_task_channel("left_y"))

    def test_profile_missing_required_joint_field_fails_closed_before_scene_load(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        urdf = Path(temporary.name) / "mobility.urdf"
        urdf.write_text(ready_urdf(), encoding="utf-8")
        manifest = ready_manifest()
        del manifest["joint_dynamics"][0]["damping"]
        scene = FakeScene(FakeLoader(FakeArticulation()))
        with (
            mock.patch.object(
                loader_module, "require_physics_ready", return_value=ready_profile(urdf)
            ),
            mock.patch.object(loader_module, "load_json_resource", return_value=manifest),
            mock.patch.object(loader_module, "resource_path", return_value=urdf),
        ):
            with self.assertRaisesRegex(RoboTwinManifestError, "missing required"):
                loader_module.load_into_scene(
                    scene,
                    SimpleNamespace(p=(0, 0, 0), q=(1, 0, 0, 0)),
                    fixed_root=True,
                    profile="test_ready",
                )
        self.assertEqual(scene.loader.paths, [])

    def test_articulation_joint_set_mismatch_fails_closed(self):
        with self.assertRaisesRegex(JointConfigurationError, "active-joint mismatch"):
            XboxOneSArticulation(
                FakeArticulation(),
                ["button_a"],
                GamepadSignalController.xbox_one_s(()),
            )

    def test_built_profile_check_rejects_urdf_without_inertial(self):
        # Explicit physics is a build-time property of generated URDFs (asset tests),
        # not a per-load check; this keeps the rule itself covered.
        from .built_profile_checks import check_explicit_urdf_physics

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        urdf = Path(temporary.name) / "mobility.urdf"
        urdf.write_text(
            ready_urdf().replace('<mass value="0.1"/>', '<!-- mass deliberately absent -->', 1),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AssertionError, "explicit inertial"):
            check_explicit_urdf_physics(urdf)

    def test_built_profile_check_rejects_non_finite_joint_target(self):
        from .built_profile_checks import check_manifest_ranges

        manifest = ready_manifest()
        manifest["joint_dynamics"][0]["target"] = float("nan")
        with self.assertRaisesRegex(AssertionError, "finite number"):
            check_manifest_ranges(manifest)

    def test_importing_robotwin_package_does_not_import_sapien(self):
        before = {name for name in sys.modules if name == "sapien" or name.startswith("sapien.")}
        import xbox_gamepad_physics.robotwin as robotwin

        importlib.reload(robotwin)
        after = {name for name in sys.modules if name == "sapien" or name.startswith("sapien.")}
        self.assertEqual(after, before)

    def test_missing_profile_fails_before_scene_mutation(self):
        scene = FakeScene(FakeLoader(FakeArticulation()))
        with self.assertRaises(ResourceNotFoundError):
            loader_module.load_into_scene(
                scene,
                SimpleNamespace(p=(0, 0, 0), q=(1, 0, 0, 0)),
                fixed_root=True,
                profile="does_not_exist",
            )
        self.assertEqual(scene.loader.paths, [])


class NativeInstallTest(unittest.TestCase):
    def test_dry_run_plans_data_copies_without_touching_robotwin(self):
        with tempfile.TemporaryDirectory() as source_directory, tempfile.TemporaryDirectory() as root_directory:
            source = Path(source_directory)
            urdf = source / "mobility.urdf"
            manifest = source / "manifest.json"
            urdf.write_text(ready_urdf(), encoding="utf-8")
            manifest.write_text("{}", encoding="utf-8")
            root = Path(root_directory)
            (root / "assets" / "objects").mkdir(parents=True)
            profile = ready_profile(urdf)

            def fake_resource_path(backend, selected, *parts, must_exist=True):
                return source.joinpath(*parts)

            with (
                mock.patch(
                    "xbox_gamepad_physics.robotwin.install.require_physics_ready",
                    return_value=profile,
                ),
                mock.patch(
                    "xbox_gamepad_physics.robotwin.install.resource_path",
                    fake_resource_path,
                ),
            ):
                result = install_native_assets(
                    root, "test_ready", dry_run=True
                )
            self.assertTrue(result.dry_run)
            self.assertEqual(len(result.operations), 2)
            self.assertFalse(result.destination.exists())
            self.assertFalse((root / "envs").exists())


if __name__ == "__main__":
    unittest.main()
