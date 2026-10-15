"""GPU integration probe for insertion into a caller-owned SAPIEN scene.

Run each shader in a separate process because shader settings are global.
The exclusion mask is defined by segmentation and vertical-light geometry,
never by the observed image difference.
"""
from __future__ import annotations

import argparse
import faulthandler
import json
import math
from pathlib import Path


def probe(shader, output=None):
    faulthandler.dump_traceback_later(90)
    import numpy as np
    from PIL import Image, ImageDraw
    import sapien
    from transforms3d.quaternions import mat2quat
    from xbox_gamepad_physics.robotwin import load_into_scene

    if sapien.__version__ != "3.0.3":
        raise RuntimeError("The insertion gate requires SAPIEN 3.0.3")
    render = sapien.render
    render.set_camera_shader_dir(shader)
    render.set_ray_tracing_samples_per_pixel(64)
    render.set_ray_tracing_path_depth(8)
    render.set_ray_tracing_denoiser("none")

    def settings():
        names = ("camera_shader_dir", "viewer_shader_dir", "msaa",
                 "ray_tracing_samples_per_pixel", "ray_tracing_path_depth",
                 "ray_tracing_denoiser", "ray_tracing_dof_aperture",
                 "ray_tracing_dof_plane")
        sdf = sapien.physx.get_sdf_config()
        return {"render": {name: getattr(render, "get_" + name)() for name in names},
                "sdf": {name: getattr(sdf, name) for name in
                        ("spacing", "subgridSize", "num_threads_for_construction")}}

    def world(with_render):
        systems = [sapien.physx.PhysxCpuSystem()]
        if with_render:
            systems.append(render.RenderSystem("cuda:0"))
        scene = sapien.Scene(systems)
        scene.set_timestep(1 / 240)
        def box(name, half_size, position, color, dynamic=False, roughness=.5):
            builder = scene.create_actor_builder()
            builder.add_box_collision(half_size=half_size)
            if with_render:
                material = render.RenderMaterial(base_color=[*color, 1],
                                                 roughness=roughness, metallic=0)
                builder.add_box_visual(half_size=half_size, material=material)
            actor = builder.build(name=name) if dynamic else builder.build_static(name=name)
            actor.set_pose(sapien.Pose(p=position))
            return actor
        box("table", [.45, .32, .025], [0, 0, -.025], [.35, .4, .45])
        actors = [box("red_falling", [.025]*3, [-.25, .08, .15], [.8, .06, .03], True),
                  box("green_falling", [.02]*3, [.25, .08, .11], [.05, .6, .12], True),
                  box("blue_resting", [.03]*3, [.26, -.12, .03], [.04, .1, .7], True)]
        if with_render:
            scene.set_ambient_light([.2]*3)
            # A vertical directional light makes the complete shadow footprint
            # the horizontal projection of the controller's actual world AABB.
            scene.add_directional_light([0, 0, -1], [1.5]*3, shadow=True,
                                        shadow_map_size=2048, shadow_scale=1)
        return scene, actors

    scene, actors = world(True)
    control, controls = world(False)
    camera = scene.add_camera("existing", 640, 480, math.radians(45), .01, 10)
    position = np.array([0, -.65, .52])
    forward = np.array([0, 0, .01]) - position
    forward /= np.linalg.norm(forward)
    left = np.cross([0, 0, 1], forward)
    left /= np.linalg.norm(left)
    camera.entity.set_pose(sapien.Pose(p=position,
        q=mat2quat(np.column_stack([forward, left, np.cross(forward, left)]))))

    def picture():
        scene.update_render()
        camera.take_picture()
        return {name: camera.get_picture(name).copy() for name in ("Color", "Position", "Segmentation")}

    before = picture()
    repeats = [picture(), picture()]
    config_before = settings()
    gamepad = load_into_scene(scene, sapien.Pose(p=[0, 0, .09]), fixed_root=True)
    config_after = settings()
    after = picture()
    links = gamepad.articulation.get_links()
    components = [component for link in links for component in link.entity.components
                  if isinstance(component, render.RenderBodyComponent)]
    ids = [component.entity.per_scene_id for component in components]
    silhouette = np.isin(after["Segmentation"][..., 1], ids)
    if not silhouette.any():
        raise AssertionError("Controller segmentation mask is empty")
    bounds = np.asarray([component.compute_global_aabb_tight() for component in components])
    lower, upper = bounds[:, 0].min(axis=0), bounds[:, 1].max(axis=0)
    points = np.array([[x, y, 0, 1] for x, y in
                       ((lower[0], lower[1]), (upper[0], lower[1]),
                        (upper[0], upper[1]), (lower[0], upper[1]))])
    view = (camera.get_extrinsic_matrix() @ points.T)[:3]
    pixels = camera.get_intrinsic_matrix() @ view
    pixels = (pixels[:2] / pixels[2]).T
    shadow_image = Image.new("L", (640, 480))
    ImageDraw.Draw(shadow_image).polygon([tuple(p) for p in pixels], fill=255)
    # Fixed in the protocol, independently of image differences; report the
    # margin separately so its shadow-filter coverage can be reviewed.
    from PIL import ImageFilter
    shadow = np.asarray(shadow_image.filter(ImageFilter.MaxFilter(5))) > 0
    excluded = silhouette | shadow
    def rgb(frame):
        return np.rint(np.clip(frame["Color"][..., :3], 0, 1)*255).astype(np.uint8)
    def difference(a, b):
        delta = np.abs(rgb(a).astype(int) - rgb(b).astype(int))
        changed = (delta != 0).any(axis=-1)
        raw = np.abs(a["Color"][..., :3] - b["Color"][..., :3])
        return {"changed_pixels": int(changed.sum()),
                "outside_changed_pixels": int((changed & ~excluded).sum()),
                "outside_max_code_delta": int(delta[~excluded].max()),
                "outside_mean_code_delta": float(delta[~excluded].mean()),
                "outside_raw_float_changed_pixels": int(((raw != 0).any(axis=-1) & ~excluded).sum()),
                "outside_raw_float_max_delta": float(raw[~excluded].max())}
    result = {"shader": shader, "sapien": sapien.__version__,
              "settings_before": config_before, "settings_after": config_after,
              "settings_equal": config_before == config_after,
              "baseline_repeats": [difference(before, frame) for frame in repeats],
              "insertion": difference(before, after),
              "controller_pixels": int(silhouette.sum()), "shadow_pixels": int(shadow.sum()),
              "excluded_pixels": int(excluded.sum()), "world_aabb_m": [lower.tolist(), upper.tolist()],
              "shadow_method": "Actual controller render-body world AABB projected vertically onto tabletop z=0; fixed 2px shadow-map filter margin. No difference-selected pixels.",
              "api_evidence": "build/experiments/v040_d1/ruling1/api/default.json and rt.json",
              "physics_steps": 0, "physics_exact": None,
              "physics_max_absolute_delta": None, "passed": False}
    if output:
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgb(before)).save(output / "before.png")
        Image.fromarray(rgb(after)).save(output / "after.png")
        Image.fromarray(silhouette.astype(np.uint8)*255).save(output / "controller_mask.png")
        Image.fromarray(shadow.astype(np.uint8)*255).save(output / "shadow_mask.png")
        Image.fromarray(excluded.astype(np.uint8)*255).save(output / "excluded.png")
        Image.fromarray(np.clip(np.abs(rgb(before).astype(int)-rgb(after).astype(int))*8, 0, 255).astype(np.uint8)).save(output / "difference_x8.png")
        changed = (rgb(before) != rgb(after)).any(axis=-1)
        Image.fromarray((changed & ~excluded).astype(np.uint8)*255).save(output / "outside_difference_mask.png")
        np.savez_compressed(output / "frames.npz", before_color=before["Color"],
                            after_color=after["Color"], before_depth=before["Position"],
                            after_depth=after["Position"], segmentation=after["Segmentation"])
        (output / "metrics.json").write_text(json.dumps(result, indent=2)+"\n")
    # ActorBuilder.build returns Entity. The API probe confirmed that velocity
    # access belongs to its PhysxRigidDynamicComponent, while pose is on Entity.
    def body(entity):
        return next(component for component in entity.components
                    if isinstance(component, sapien.physx.PhysxRigidDynamicComponent))
    bodies = [body(actor) for actor in actors]
    control_bodies = [body(actor) for actor in controls]
    physics_max_delta = 0.
    physics_exact = True
    trajectories = []
    for _ in range(80):
        control.step()
        scene.step()
        states = []
        for a, b, dynamic_a, dynamic_b in zip(actors, controls, bodies, control_bodies):
            va = np.r_[a.pose.p, a.pose.q, dynamic_a.get_linear_velocity(), dynamic_a.get_angular_velocity()]
            vb = np.r_[b.pose.p, b.pose.q, dynamic_b.get_linear_velocity(), dynamic_b.get_angular_velocity()]
            physics_exact &= bool(np.array_equal(va, vb))
            physics_max_delta = max(physics_max_delta, float(np.abs(va-vb).max()))
            states.append([va.tolist(), vb.tolist()])
        trajectories.append(states)
    result.update(physics_steps=80, physics_exact=physics_exact,
                  physics_max_absolute_delta=physics_max_delta)
    pixels_equal = (result["insertion"]["outside_changed_pixels"] == 0 and
                    result["insertion"]["outside_raw_float_changed_pixels"] == 0)
    # RT light transport changes when geometry is inserted. Its neutral-object
    # comparison is an experiment reported separately, not a unit-test gate.
    result["pixel_invariance_passed"] = pixels_equal
    result["passed"] = (result["settings_equal"] and physics_exact and
                        (shader == "rt" or pixels_equal))
    if output:
        (output / "physics.json").write_text(json.dumps(trajectories)+"\n")
        (output / "metrics.json").write_text(json.dumps(result, indent=2)+"\n")
    faulthandler.cancel_dump_traceback_later()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shader", choices=("default", "rt"), required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    print(json.dumps(probe(args.shader, args.output), indent=2))
