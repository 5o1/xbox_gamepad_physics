"""The public integration path is discoverable and diagnostics are read-only."""
import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from xbox_gamepad_physics import cli, integration
from xbox_gamepad_physics.robotwin import diagnostics, scene as public_scene


class Entity:
    def __init__(self, name="", components=(), pose=None):
        self.name, self.components, self.pose = name, components, pose


class Articulation:
    name = "test"

    def __init__(self, entity):
        self.entity = entity

    def get_links(self):
        return [NS(name="controller_body", entity=self.entity)]

    def get_active_joints(self):
        return [NS(name="left_stick_x")]


class DiagnosticTest(unittest.TestCase):
    def make_scene(self):
        root = Entity("controller_body", pose=NS(p=[0, 0, 0.8]))
        art = Articulation(root)
        scene = NS(create_urdf_loader=lambda: None,
                   get_all_articulations=lambda: [art], get_entities=lambda: [root])
        fake = NS(physx=NS(PhysxCollisionShapePlane=type("Plane", (), {})),
                  render=NS(get_camera_shader_dir=lambda: "/shaders/default"))
        return scene, art, fake

    def test_direct_urdf_and_official_load_are_distinguished(self):
        scene, art, fake = self.make_scene()
        with mock.patch.object(diagnostics, "require_sapien", return_value=fake):
            result = diagnostics.diagnose_scene(scene)
            self.assertFalse(result["gamepads"][0]["via_load_into_scene"])
            self.assertIn("direct_urdf", [item["code"] for item in result["findings"]])
            diagnostics._mark_loaded(scene, art, profile="full_controls", collision="sdf", attach_visual=True)
            before = dict(scene.__dict__)
            result = diagnostics.diagnose_scene(scene)
            self.assertEqual(result["findings"], [])
            self.assertTrue(result["gamepads"][0]["via_load_into_scene"])
            self.assertEqual(scene.__dict__, before)

    def test_add_ground_below_sdf_and_direct_mesh_are_reported(self):
        scene, art, fake = self.make_scene()
        diagnostics._mark_loaded(scene, art, profile="full_controls", collision="sdf", attach_visual=True)
        plane = fake.physx.PhysxCollisionShapePlane()
        plane.local_pose = object()
        class PlanePose:
            p = [0, 0, 0]
            def __mul__(self, other):
                return self
            def to_transformation_matrix(self):
                return [[0, 0, 0, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1]]
        ground = Entity("ground", [NS(collision_shapes=[plane])], PlanePose())
        raw = Entity("raw", [NS(render_shapes=[NS(filename="/resources/common/xbox_one_s/sim_visual/body.obj")])])
        scene.get_entities = lambda: [art.entity, ground, raw]
        with mock.patch.object(diagnostics, "require_sapien", return_value=fake):
            result = diagnostics.diagnose_scene(scene)
        self.assertEqual({item["code"] for item in result["findings"]}, {"sdf_plane_support", "direct_mesh"})
        self.assertEqual(result["rendering"]["mode"], "raster")

    def test_coacd_does_not_claim_sdf_plane_problem(self):
        scene, art, fake = self.make_scene()
        diagnostics._mark_loaded(scene, art, profile="full_controls", collision="coacd", attach_visual=True)
        fake.render.get_camera_shader_dir = lambda: "/shaders/rt"
        with mock.patch.object(diagnostics, "require_sapien", return_value=fake):
            result = diagnostics.diagnose_scene(scene)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["rendering"]["mode"], "ray_tracing")


class EntryPointTest(unittest.TestCase):
    def test_doctor_missing_runtime_and_resources_has_actionable_result(self):
        with mock.patch.object(integration, "_version", return_value=None), mock.patch.object(integration, "resource_status", return_value={"root": "/tmp/test", "missing": ["a"], "nodes": [{"name": "visual", "stale": True}]}):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = cli.main(["doctor", "--json"])
        result = json.loads(stream.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(result["sdf_supported"])
        self.assertFalse(result["resources"]["ready"])
        self.assertFalse(result["extras"]["example"]["installed"])

    def test_doctor_ready_and_old_sapien(self):
        with mock.patch.object(integration, "_version", return_value="3.0.3"), mock.patch.object(integration, "resource_status", return_value={"root": "/tmp/test", "missing": [], "nodes": []}):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["doctor"]), 0)
        with mock.patch.object(integration, "_version", return_value="3.0.0b1"), mock.patch.object(integration, "resource_status", return_value={"missing": [], "nodes": []}):
            self.assertFalse(integration.diagnose_environment()["sdf_supported"])

    def test_newer_sapien_capability_does_not_claim_supported_baseline(self):
        with mock.patch.object(integration, "_version", return_value="4.0.0"), mock.patch.object(integration, "resource_status", return_value={"missing": [], "nodes": []}):
            result = integration.diagnose_environment()
        self.assertTrue(result["sdf_supported"])
        self.assertFalse(result["supported_sapien"])

    def test_guide_and_help_expose_the_correct_path(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["guide"]), 0)
        for token in ("load_into_scene", "example export", "GLOBAL", "static box", "doctor", "channel name"):
            self.assertIn(token, output.getvalue())
        help_text = cli._parser().format_help()
        for token in ("guide", "example export", "doctor"):
            self.assertIn(token, help_text[:700])

    def test_public_scene_does_not_apply_global_settings(self):
        sapien = mock.MagicMock()
        with mock.patch.object(public_scene, "require_sapien", return_value=sapien):
            result = public_scene.create_scene()
        self.assertIs(result, sapien.Engine.return_value.create_scene.return_value)
        self.assertEqual(sapien.render.mock_calls, [])
        sapien.physx.set_sdf_config.assert_not_called()
