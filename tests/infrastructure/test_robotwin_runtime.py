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
from xbox_gamepad_physics.errors import PhysicsNotReadyError
from xbox_gamepad_physics.robotwin.articulation import (
    AxisMapping,
    RadialGroup,
    XboxOneSArticulation,
)
from xbox_gamepad_physics.robotwin.errors import (
    JointConfigurationError,
    RoboTwinManifestError,
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
                    "channel": "lx",
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
    def _load(self, *, use_multiple=True, task_wrapper=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        urdf = Path(temporary.name).resolve() / "mobility.urdf"
        urdf.write_text(ready_urdf(), encoding="utf-8")
        articulation = FakeArticulation()
        fake_loader = FakeLoader(articulation, use_multiple=use_multiple)
        scene = FakeScene(fake_loader)
        passed_scene = SimpleNamespace(scene=scene) if task_wrapper else scene
        pose = SimpleNamespace(p=(1, 2, 3), q=(1, 0, 0, 0))

        def fake_resource_path(backend, profile, *parts, must_exist=True):
            self.assertEqual((backend, profile), ("robotwin", "test_ready"))
            self.assertEqual(parts, ("mobility.urdf",))
            return urdf

        with (
            mock.patch.object(
                loader_module, "require_physics_ready", return_value=ready_profile(urdf)
            ),
            mock.patch.object(
                loader_module, "load_json_resource", return_value=ready_manifest()
            ),
            mock.patch.object(loader_module, "resource_path", fake_resource_path),
            mock.patch.object(
                loader_module, "_import_sapien", side_effect=AssertionError("eager import")
            ),
            mock.patch(
                "xbox_gamepad_physics.robotwin.visual.attach_visual_to_articulation"
            ),
        ):
            wrapper = loader_module.load_into_scene(
                passed_scene, pose, fixed_root=True, profile="test_ready"
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

    def test_robotwin_task_scene_and_single_load_fallback_are_supported(self):
        wrapper, _, fake_loader, _, _ = self._load(
            use_multiple=False, task_wrapper=True
        )
        self.assertEqual(wrapper.joint_names, ("button_a", "left_stick_x"))
        self.assertEqual(len(fake_loader.paths), 1)

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
                scene, pose, fixed_root=True, profile="test_ready"
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
        wrapper = XboxOneSArticulation(
            articulation,
            ["button_a", "left_stick_x"],
            [
                AxisMapping("lx", "button_a", -0.4, 0.4),
                AxisMapping("ly", "left_stick_x", -0.4, 0.4),
            ],
            [RadialGroup(("lx", "ly"), 1.0)],
        )
        state = wrapper.gamepad_state()
        self.assertAlmostEqual(state.lx, 2 ** -0.5)
        self.assertAlmostEqual(state.ly, 2 ** -0.5)
        self.assertEqual(state.rx, 0.0)

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
            XboxOneSArticulation(FakeArticulation(), ["button_a"])

    def test_urdf_missing_inertial_fails_before_scene_mutation(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        urdf = Path(temporary.name) / "mobility.urdf"
        urdf.write_text(
            ready_urdf().replace(
                '<mass value="0.1"/>', '<!-- mass deliberately absent -->', 1
            ),
            encoding="utf-8",
        )
        scene = FakeScene(FakeLoader(FakeArticulation()))
        with (
            mock.patch.object(
                loader_module, "require_physics_ready", return_value=ready_profile(urdf)
            ),
            mock.patch.object(
                loader_module, "load_json_resource", return_value=ready_manifest()
            ),
            mock.patch.object(loader_module, "resource_path", return_value=urdf),
        ):
            with self.assertRaisesRegex(RoboTwinManifestError, "explicit inertial"):
                loader_module.load_into_scene(
                    scene,
                    SimpleNamespace(p=(0, 0, 0), q=(1, 0, 0, 0)),
                    fixed_root=True,
                    profile="test_ready",
                )
        self.assertEqual(scene.loader.paths, [])

    def test_importing_robotwin_package_does_not_import_sapien(self):
        before = {name for name in sys.modules if name == "sapien" or name.startswith("sapien.")}
        import xbox_gamepad_physics.robotwin as robotwin

        importlib.reload(robotwin)
        after = {name for name in sys.modules if name == "sapien" or name.startswith("sapien.")}
        self.assertEqual(after, before)

    def test_checked_in_estimated_profile_is_blocked_before_scene_mutation(self):
        scene = FakeScene(FakeLoader(FakeArticulation()))
        with self.assertRaisesRegex(PhysicsNotReadyError, "blocked"):
            loader_module.load_into_scene(
                scene,
                SimpleNamespace(p=(0, 0, 0), q=(1, 0, 0, 0)),
                fixed_root=True,
                profile="estimated_v0",
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
