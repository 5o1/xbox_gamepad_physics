from __future__ import annotations

import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xbox_gamepad_physics.errors import (  # noqa: E402
    AssetImportError,
    MissingBackendDependencyError,
    MissingResourceError,
    PhysicsNotReadyError,
)
from xbox_gamepad_physics.mujoco._manifest import RuntimeManifest  # noqa: E402


backend_module = importlib.import_module("xbox_gamepad_physics.mujoco._backend")
attach_module = importlib.import_module("xbox_gamepad_physics.mujoco.attach")
loader_module = importlib.import_module("xbox_gamepad_physics.mujoco.loader")


class _JointModelView:
    def __init__(self, name):
        self.name = name


class _JointDataView:
    def __init__(self, name):
        self.name = name
        self.qpos = [0.25]
        self.qvel = [-0.5]


class _SensorModelView:
    def __init__(self, name):
        self.name = name


class _SensorDataView:
    def __init__(self, name):
        self.name = name
        self.data = [0.75]


class _FakeModel:
    def __init__(self, joints, sensors):
        self._joints = set(joints)
        self._sensors = set(sensors)

    def joint(self, name):
        if name not in self._joints:
            raise KeyError(name)
        return _JointModelView(name)

    def sensor(self, name):
        if name not in self._sensors:
            raise KeyError(name)
        return _SensorModelView(name)


class _FakeData:
    def __init__(self, model):
        self._model = model

    def joint(self, name):
        self._model.joint(name)
        return _JointDataView(name)

    def sensor(self, name):
        self._model.sensor(name)
        return _SensorDataView(name)


class _FakeSpec:
    def __init__(self, model):
        self._model = model

    def compile(self):
        return self._model


class _FakeMjSpecFactory:
    calls = []
    next_model = None

    @classmethod
    def from_file(cls, path):
        cls.calls.append(("xml", path))
        return _FakeSpec(cls.next_model)

    @classmethod
    def from_zip(cls, path):
        cls.calls.append(("mjz", path))
        return _FakeSpec(cls.next_model)


class _FakeMujoco:
    MjSpec = _FakeMjSpecFactory
    MjData = _FakeData


def _manifest(*, entrypoint="xbox_one_s.xml", scene_file="scene_fixed.xml"):
    return RuntimeManifest(
        profile="estimated_v0",
        entrypoint=entrypoint,
        scenes={"fixed": scene_file},
        joints={"left_stick_x": "left_stick_x_joint"},
        sensors={"left_stick_x_position": "left_stick_x_sensor"},
    )


class MujocoRuntimeTests(unittest.TestCase):
    def setUp(self):
        _FakeMjSpecFactory.calls = []

    def test_backend_import_is_lazy_and_uses_project_error(self):
        # Importing the public package above did not import MuJoCo. The optional
        # dependency is consulted only when a runtime operation requests it.
        with mock.patch.object(
            backend_module.importlib,
            "import_module",
            side_effect=ModuleNotFoundError("No module named 'mujoco'"),
        ):
            with self.assertRaises(MissingBackendDependencyError) as raised:
                backend_module.require_mujoco()
        self.assertIn("optional 'mujoco'", str(raised.exception))

    def test_checked_in_placeholder_fails_before_backend_import(self):
        with mock.patch.object(loader_module, "require_mujoco") as import_backend:
            with self.assertRaisesRegex(PhysicsNotReadyError, "dynamics_ready=False"):
                loader_module.load_scene()
        import_backend.assert_not_called()

    def test_load_scene_compiles_xml_and_binds_names(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scene_fixed.xml"
            source.write_text("<mujoco/>", encoding="utf-8")
            _FakeMjSpecFactory.next_model = _FakeModel(
                ["left_stick_x_joint"], ["left_stick_x_sensor"]
            )

            with (
                mock.patch.object(
                    loader_module, "load_runtime_manifest", return_value=_manifest()
                ),
                mock.patch.object(loader_module, "resolve_resource", return_value=source),
                mock.patch.object(loader_module, "require_mujoco", return_value=_FakeMujoco),
            ):
                loaded = loader_module.load_scene()

        self.assertEqual(_FakeMjSpecFactory.calls, [("xml", str(source))])
        self.assertEqual(loaded.gamepad.joint_names["left_stick_x"], "left_stick_x_joint")
        self.assertEqual(loaded.gamepad.joint_qpos("left_stick_x"), [0.25])
        self.assertEqual(
            loaded.gamepad.sensor_value("left_stick_x_position"), [0.75]
        )

    def test_load_scene_accepts_mjz_declared_by_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scene_fixed.mjz"
            source.write_bytes(b"fake zip for mocked MuJoCo")
            _FakeMjSpecFactory.next_model = _FakeModel(
                ["left_stick_x_joint"], ["left_stick_x_sensor"]
            )

            with (
                mock.patch.object(
                    loader_module,
                    "load_runtime_manifest",
                    return_value=_manifest(scene_file="scene_fixed.mjz"),
                ),
                mock.patch.object(loader_module, "resolve_resource", return_value=source),
                mock.patch.object(loader_module, "require_mujoco", return_value=_FakeMujoco),
            ):
                loader_module.load_scene()

        self.assertEqual(_FakeMjSpecFactory.calls, [("mjz", str(source))])

    def test_load_scene_propagates_missing_resource_without_importing_backend(self):
        missing = MissingResourceError("scene file is absent")
        with (
            mock.patch.object(
                loader_module, "load_runtime_manifest", return_value=_manifest()
            ),
            mock.patch.object(loader_module, "resolve_resource", side_effect=missing),
            mock.patch.object(loader_module, "require_mujoco") as import_backend,
        ):
            with self.assertRaises(MissingResourceError):
                loader_module.load_scene()
        import_backend.assert_not_called()

    def test_attach_to_frame_preserves_prefix_and_binds_after_compile(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "xbox_one_s.xml"
            source.write_text("<mujoco/>", encoding="utf-8")
            child_model = _FakeModel(
                ["left_stick_x_joint"], ["left_stick_x_sensor"]
            )
            parent_model = _FakeModel(
                ["pad_left_stick_x_joint"], ["pad_left_stick_x_sensor"]
            )
            _FakeMjSpecFactory.next_model = child_model
            parent = _FakeParentSpec(parent_model)

            with (
                mock.patch.object(
                    attach_module, "load_runtime_manifest", return_value=_manifest()
                ),
                mock.patch.object(attach_module, "resolve_resource", return_value=source),
                mock.patch.object(attach_module, "require_mujoco", return_value=_FakeMujoco),
            ):
                attachment = attach_module.attach_to_spec(
                    parent, frame="gamepad_mount", prefix="pad_"
                )
                compiled = attachment.compile()

        self.assertEqual(
            parent.attach_calls,
            [
                {
                    "child": attachment.child_spec,
                    "frame": "gamepad_mount",
                    "prefix": "pad_",
                    "suffix": "",
                }
            ],
        )
        self.assertEqual(
            compiled.gamepad.joint_names["left_stick_x"],
            "pad_left_stick_x_joint",
        )
        self.assertEqual(compiled.gamepad.joint_qvel("left_stick_x"), [-0.5])

    def test_attach_to_site_and_external_bind_use_named_elements(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "xbox_one_s.mjz"
            source.write_bytes(b"fake zip for mocked MuJoCo")
            _FakeMjSpecFactory.next_model = _FakeModel([], [])
            parent = _FakeParentSpec(None)

            with (
                mock.patch.object(
                    attach_module,
                    "load_runtime_manifest",
                    return_value=_manifest(entrypoint="xbox_one_s.mjz"),
                ),
                mock.patch.object(attach_module, "resolve_resource", return_value=source),
                mock.patch.object(attach_module, "require_mujoco", return_value=_FakeMujoco),
            ):
                attachment = attach_module.attach_to_spec(
                    parent, site="fixture_site", prefix="left_", suffix="_0"
                )

            model = _FakeModel(
                ["left_left_stick_x_joint_0"],
                ["left_left_stick_x_sensor_0"],
            )
            handle = attachment.bind(model, _FakeData(model))

        self.assertEqual(_FakeMjSpecFactory.calls, [("mjz", str(source))])
        self.assertEqual(handle.joint("left_stick_x").name, "left_left_stick_x_joint_0")
        self.assertEqual(parent.attach_calls[0]["site"], "fixture_site")

    def test_attach_requires_exactly_one_target_and_nonempty_prefix(self):
        parent = _FakeParentSpec(None)
        with self.assertRaisesRegex(ValueError, "Exactly one"):
            attach_module.attach_to_spec(parent)
        with self.assertRaisesRegex(ValueError, "Exactly one"):
            attach_module.attach_to_spec(parent, frame="f", site="s")
        with self.assertRaisesRegex(ValueError, "prefix"):
            attach_module.attach_to_spec(parent, frame="f", prefix="")

    def test_missing_compiled_name_fails_instead_of_using_an_index(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scene_fixed.xml"
            source.write_text("<mujoco/>", encoding="utf-8")
            _FakeMjSpecFactory.next_model = _FakeModel([], [])
            with (
                mock.patch.object(
                    loader_module, "load_runtime_manifest", return_value=_manifest()
                ),
                mock.patch.object(loader_module, "resolve_resource", return_value=source),
                mock.patch.object(loader_module, "require_mujoco", return_value=_FakeMujoco),
            ):
                with self.assertRaisesRegex(AssetImportError, "left_stick_x_joint"):
                    loader_module.load_scene()


class _FakeParentSpec:
    def __init__(self, model):
        self._model = model
        self.attach_calls = []

    def attach(self, child, **kwargs):
        call = {"child": child, **kwargs}
        self.attach_calls.append(call)
        return SimpleNamespace(name="attached_world_frame")

    def compile(self):
        return self._model


if __name__ == "__main__":
    unittest.main()
