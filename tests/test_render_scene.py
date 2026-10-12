"""The extracted renderer retains existing defaults and shared light settings."""
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch
from experiments.scene import create_render_scene, create_scene


class SharedSceneTest(unittest.TestCase):
    def build(self, **settings):
        sapien = ModuleType("sapien")
        render = ModuleType("sapien.render")
        render.set_global_config = MagicMock()
        for name in ("set_camera_shader_dir", "set_ray_tracing_samples_per_pixel",
                     "set_ray_tracing_path_depth", "set_ray_tracing_denoiser"):
            setattr(render, name, MagicMock())
        sapien.render = render
        sapien.Engine = MagicMock()
        sapien.SapienRenderer = MagicMock()
        sapien.SceneConfig = MagicMock()
        scene = sapien.Engine.return_value.create_scene.return_value
        with patch.dict(sys.modules, {"sapien": sapien, "sapien.render": render}), \
                patch("experiments.scene.os.chdir"), patch.object(sys, "path", sys.path.copy()):
            result = create_render_scene({"robotwin_root": ".", "timestep": .004}, **settings)
        self.assertIs(result, scene)
        render.set_global_config.assert_called_once_with(max_num_materials=50000, max_num_textures=50000)
        sapien.Engine.return_value.set_renderer.assert_called_once_with(sapien.SapienRenderer.return_value)
        scene.set_timestep.assert_called_once_with(.004)
        scene.set_ambient_light.assert_called_once_with([.5, .5, .5])
        scene.add_directional_light.assert_called_once_with([0, .5, -1], [.5, .5, .5], shadow=True)
        self.assertEqual(scene.add_point_light.call_count, 2)
        scene.add_point_light.assert_any_call([1, 0, 1.8], [1, 1, 1], shadow=True)
        scene.add_point_light.assert_any_call([-1, 0, 1.8], [1, 1, 1], shadow=True)
        render.set_ray_tracing_path_depth.assert_called_once_with(8)
        return render

    def test_existing_rt_defaults_unchanged(self):
        render = self.build()
        render.set_camera_shader_dir.assert_called_once_with("rt")
        render.set_ray_tracing_samples_per_pixel.assert_called_once_with(4)
        render.set_ray_tracing_denoiser.assert_called_once_with("oidn")

    def test_raster_and_low_sample_rt_share_all_other_settings(self):
        render = self.build(shader="default")
        render.set_camera_shader_dir.assert_called_once_with("default")
        render = self.build(samples_per_pixel=1, denoiser="oidn")
        render.set_ray_tracing_samples_per_pixel.assert_called_once_with(1)

    def test_create_scene_uses_defaults_and_preserves_ground(self):
        cfg = {"render": True, "ground": True}
        with patch("experiments.scene.create_render_scene") as factory:
            self.assertIs(create_scene(cfg), factory.return_value)
            factory.assert_called_once_with(cfg)
            factory.return_value.add_ground.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
