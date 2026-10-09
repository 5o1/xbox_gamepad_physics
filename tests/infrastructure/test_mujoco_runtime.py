from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xbox_gamepad_physics.errors import (  # noqa: E402
    AssetImportError,
    MissingBackendDependencyError,
    MissingResourceError,
)
from xbox_gamepad_physics.mujoco._manifest import RuntimeManifest  # noqa: E402


backend_module = importlib.import_module("xbox_gamepad_physics.mujoco._backend")
attach_module = importlib.import_module("xbox_gamepad_physics.mujoco.attach")
loader_module = importlib.import_module("xbox_gamepad_physics.mujoco.loader")
visual_module = importlib.import_module("xbox_gamepad_physics.mujoco.visual")


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
    forward_calls = []

    @classmethod
    def mj_forward(cls, model, data):
        cls.forward_calls.append((model, data))


def _manifest(*, entrypoint="xbox_one_s.xml", scene_file="scene_fixed.xml"):
    return RuntimeManifest(
        profile="full_controls",
        entrypoint=entrypoint,
        scenes={"fixed": scene_file},
        joints={"left_stick_x": "left_stick_x_joint"},
        sensors={"left_stick_x_position": "left_stick_x_sensor"},
    )


class MujocoRuntimeTests(unittest.TestCase):
    def setUp(self):
        _FakeMjSpecFactory.calls = []
        _FakeMujoco.forward_calls = []

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

    def test_visual_scene_runs_forward_before_first_render(self):
        model = _FakeModel([], [])
        _FakeMjSpecFactory.next_model = model
        with mock.patch.object(
            visual_module, "require_mujoco", return_value=_FakeMujoco
        ):
            loaded = visual_module.load_visual_scene(scene="table")

        self.assertFalse(loaded.physics_ready)
        self.assertEqual(loaded.renderer, "classic")
        self.assertEqual(len(_FakeMujoco.forward_calls), 1)
        self.assertIs(_FakeMujoco.forward_calls[0][0], model)
        self.assertEqual(_FakeMjSpecFactory.calls[0][0], "xml")

    def test_filament_reference_scene_uses_declared_renderer_resource(self):
        _FakeMjSpecFactory.next_model = _FakeModel([], [])
        with mock.patch.object(
            visual_module, "require_mujoco", return_value=_FakeMujoco
        ):
            loaded = visual_module.load_visual_scene(
                scene="reference", renderer="filament"
            )

        self.assertEqual(loaded.renderer, "filament")
        self.assertEqual(loaded.source_path.name, "reference_scene_filament.xml")
        with self.assertRaisesRegex(ValueError, "unknown MuJoCo visual renderer"):
            visual_module.load_visual_scene(renderer="does-not-exist")

    def test_visual_attachment_compiles_and_runs_forward(self):
        model = _FakeModel([], [])
        _FakeMjSpecFactory.next_model = _FakeModel([], [])
        parent = _FakeParentSpec(model)
        with mock.patch.object(
            visual_module, "require_mujoco", return_value=_FakeMujoco
        ):
            attachment = visual_module.attach_visual_to_spec(
                parent, frame="gamepad_mount", prefix="pad_"
            )
            compiled_model, data = attachment.compile()

        self.assertFalse(attachment.physics_ready)
        self.assertIs(compiled_model, model)
        self.assertEqual(_FakeMujoco.forward_calls, [(model, data)])
        self.assertEqual(parent.attach_calls[0]["prefix"], "pad_")

    def test_visual_resources_are_complete_and_render_only(self):
        root = (
            SRC
            / "xbox_gamepad_physics"
            / "resource_data"
            / "mujoco"
            / "visual_v0"
        )
        manifest = json.loads(
            (root / "visual_manifest.json").read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["physics_ready"])
        self.assertEqual(len(manifest["parts"]), 16)
        self.assertTrue((root / manifest["entrypoint"]).is_file())
        self.assertTrue((root / manifest["scenes"]["table"]).is_file())
        self.assertEqual(set(manifest["renderers"]), {"classic", "filament"})
        for renderer in manifest["renderers"].values():
            self.assertTrue((root / renderer["entrypoint"]).is_file())
            for scene in renderer["scenes"].values():
                self.assertTrue((root / scene).is_file())
        for part in manifest["parts"]:
            self.assertTrue((root / "meshes" / part["file"]).is_file())

        tree = ET.parse(root / manifest["entrypoint"])
        visual_geoms = tree.findall(".//geom")
        self.assertEqual(len(visual_geoms), 16)
        self.assertFalse(tree.findall(".//joint"))
        for geom in visual_geoms:
            self.assertEqual(geom.get("contype"), "0")
            self.assertEqual(geom.get("conaffinity"), "0")

        filament = ET.parse(root / manifest["renderers"]["filament"]["entrypoint"])
        xbox_materials = {
            material.get("name"): material
            for material in filament.findall(".//material")
            if material.get("name", "").startswith("xbox_surface")
        }
        roles = {
            layer.get("role")
            for material in xbox_materials.values()
            for layer in material.findall("layer")
        }
        self.assertEqual(
            roles,
            {
                "rgb",
                "opacity",
                "normal",
                "occlusion",
                "roughness",
                "metallic",
                "emissive",
            },
        )
        self.assertNotIn(
            "opacity",
            {layer.get("role") for layer in xbox_materials["xbox_surface_opaque"].findall("layer")},
        )
        self.assertIn(
            "opacity",
            {layer.get("role") for layer in xbox_materials["xbox_surface_transparent"].findall("layer")},
        )
        requirement = manifest["filament_material"]["renderer_requirement"]
        self.assertEqual(requirement["branch"], "concon/filament-opacity-texture")


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
