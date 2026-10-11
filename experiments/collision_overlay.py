"""N4: approved RoboTwin RT appearance with translucent, coloured CoACD hulls."""
import json

from .scene import create_camera, take_picture


def run(cfg, ctx):
    import numpy as np
    import sapien
    import trimesh
    from xbox_gamepad_physics.resources import resource_path
    manifest = json.loads(resource_path("robotwin", cfg["profile"], "collision/manifest.json").read_text())
    rng = np.random.default_rng(0)
    # hulls_only: drop the visual mesh and draw opaque hulls, so each hull's extent is visible.
    hulls_only = bool(cfg["params"].get("hulls_only", False))
    alpha = 1.0 if hulls_only else 0.25
    count = 0
    for link in ctx.gamepad.articulation.get_links():
        if not manifest["links"][link.name]["coacd"]:
            continue
        body = link.entity.find_component_by_type(sapien.render.RenderBodyComponent)
        entity = link.entity
        entity.remove_component(body)
        if hulls_only:
            body = sapien.render.RenderBodyComponent()
        for relative in manifest["links"][link.name]["coacd"]:
            objects, vertices, faces, offset = [], [], [], 0
            for line in resource_path("robotwin", cfg["profile"], relative).read_text().splitlines():
                fields = line.split()
                if fields[0] == "o":
                    if vertices:
                        objects.append((vertices, faces))
                        offset += len(vertices)
                    vertices, faces = [], []
                elif fields[0] == "v":
                    vertices.append([float(x) for x in fields[1:]])
                elif fields[0] == "f":
                    faces.append([int(x)-1-offset for x in fields[1:]])
            objects.append((vertices, faces))
            for vertices, faces in objects:
                mesh = trimesh.Trimesh(vertices, faces, process=False)
                material = sapien.render.RenderMaterial(base_color=[*rng.uniform(0.15, 0.95, 3), alpha], roughness=0.5)
                shape = sapien.render.RenderShapeTriangleMesh(
                    np.asarray(mesh.vertices, dtype=np.float32), np.asarray(mesh.faces, dtype=np.uint32),
                    np.asarray(mesh.vertex_normals, dtype=np.float32), np.zeros((len(mesh.vertices), 2), dtype=np.float32), material)
                body.attach(shape)
                count += 1
        entity.add_component(body)
    camera_cfg = cfg["params"]["camera"]
    images = []
    views = [("front", [0, -0.001, 0.34]), ("back", [0, -0.001, -0.34]), ("top", [0, 0.34, 0.015])]
    if hulls_only:
        views += [("oblique_front", [0.16, -0.22, 0.2]), ("oblique_back", [-0.16, 0.22, -0.2])]
    for view, position in views:
        camera = create_camera(ctx.scene, {**camera_cfg, "position": position, "target": [0, 0, 0]})
        image = ctx.output_dir / f"{view}.png"
        take_picture(ctx.scene, camera, image)
        images.append(str(image))
    return {"hulls": count, "images": images, "opacity": alpha, "hulls_only": hulls_only, "random_seed": 0,
            "visual_acceptance": "pending_owner_review"}
