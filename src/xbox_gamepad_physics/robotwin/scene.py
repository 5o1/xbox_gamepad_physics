"""Public scene construction and opt-in review rendering helpers."""

from __future__ import annotations


def require_sapien():
    """Import SAPIEN lazily so inspection commands need no GPU runtime."""
    from xbox_gamepad_physics.errors import MissingBackendDependencyError
    try:
        import sapien
    except ModuleNotFoundError as error:
        if error.name != "sapien":
            raise
        raise MissingBackendDependencyError(
            "This operation requires SAPIEN 3.0.3; install the [robotwin] extra."
        ) from error
    return sapien


def apply_review_rendering(*, shader="rt", samples_per_pixel=4, denoiser="oidn"):
    """Opt in to the renderer settings used for the package's review images.

    This changes SAPIEN GLOBAL camera shaders, renderer resource limits and
    ray-tracing settings, affecting all cameras in all scenes in this process.
    Call before creating the renderer/cameras, only to reproduce review images.
    Loading a gamepad and normal raster inspection do not require this helper.
    """
    if shader not in ("rt", "default") or samples_per_pixel < 1:
        raise ValueError("expected rt/default shader and positive samples_per_pixel")
    render = require_sapien().render
    render.set_global_config(max_num_materials=50000, max_num_textures=50000)
    render.set_camera_shader_dir(shader)
    render.set_ray_tracing_samples_per_pixel(samples_per_pixel)
    render.set_ray_tracing_path_depth(8)
    render.set_ray_tracing_denoiser(denoiser)


def create_scene(*, timestep=0.004, render=True, lighting=True):
    """Create a standalone SAPIEN scene with optional review-style lighting.

    Uses the caller's current global renderer settings (SAPIEN defaults to
    rasterization); never selects a global shader or changes PhysX SDF settings.
    For an existing experiment, pass its scene directly to ``load_into_scene``.
    No support plane is added: SDF support must be a static box, not add_ground.
    ``apply_review_rendering`` is a separate, explicitly global opt-in.
    """
    sapien = require_sapien()
    if render:
        engine = sapien.Engine()
        renderer = sapien.SapienRenderer()
        engine.set_renderer(renderer)
        scene = engine.create_scene(sapien.SceneConfig())
    else:
        scene = sapien.Scene()
    scene.set_timestep(timestep)
    if render and lighting:
        scene.set_ambient_light([0.5, 0.5, 0.5])
        scene.add_directional_light([0, 0.5, -1], [0.5, 0.5, 0.5], shadow=True)
        scene.add_point_light([1, 0, 1.8], [1, 1, 1], shadow=True)
        scene.add_point_light([-1, 0, 1.8], [1, 1, 1], shadow=True)
    return scene
