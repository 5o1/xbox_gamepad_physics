"""Blender CPU preview of native-unit source geometry, not a simulation render.

Camera, lighting and exploded offsets are visualization choices, never exported
as physical parameters. Color groups use original object names, not inferred DOFs.
"""

import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def main():
    folder = Path(sys.argv[sys.argv.index("--") + 1])
    manifest = json.loads((folder / "inventory.json").read_text())
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    groups = {}
    all_points = []
    for item in manifest["objects"]:
        if item["type"] != "MESH":
            continue
        vertices, faces = [], []
        for line in (folder / item["file"]).read_text().splitlines():
            if line.startswith("v "):
                vertices.append(tuple(map(float, line.split()[1:])))
            elif line.startswith("f "):
                faces.append(tuple(int(x) - 1 for x in line.split()[1:]))
        data = bpy.data.meshes.new(item["name"])
        data.from_pydata(vertices, [], faces)
        obj = bpy.data.objects.new(item["name"], data)
        bpy.context.collection.objects.link(obj)
        name = item["name"]
        group = (
            "shell"
            if name.startswith(("MainBody", "Battery", "USB", "Logo", "Joystick-"))
            else "sticks"
            if "Thumb" in name
            else "dpad"
            if "DPad" in name
            else "shoulders_triggers"
            if "Shoulder" in name
            else "buttons"
        )
        colors = {
            "shell": (0.22, 0.27, 0.33, 1),
            "sticks": (0.10, 0.60, 0.82, 1),
            "dpad": (0.85, 0.47, 0.12, 1),
            "shoulders_triggers": (0.5, 0.3, 0.7, 1),
            "buttons": (0.17, 0.7, 0.38, 1),
        }
        mat = bpy.data.materials.get(group) or bpy.data.materials.new(group)
        mat.diffuse_color = colors[group]
        obj.data.materials.append(mat)
        groups[name] = group
        all_points.extend(Vector(v) for v in vertices)
    lo = Vector([min(v[i] for v in all_points) for i in range(3)])
    hi = Vector([max(v[i] for v in all_points) for i in range(3)])
    center, size = (lo + hi) / 2, (hi - lo).length
    bpy.ops.object.camera_add(location=center + Vector((0, -0.65, 1.3)) * size)
    camera = bpy.context.object
    camera.rotation_euler = (
        (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    camera.rotation_euler.rotate_axis("Z", math.pi)
    review = '--identity-review' in sys.argv
    if review:
        camera.location = center + Vector((0, -2, 0)) * size
        camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = size * 1.05
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.background_type = "WORLD"
    scene.world.color = (0.04, 0.04, 0.04)
    scene.render.resolution_x = 1000
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(folder / ("identity_front.png" if review else "parts_preview.png"))
    bpy.ops.render.render(write_still=True)
    if review:
        camera.location = center + Vector((0, 0, 2)) * size
        camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(folder / 'identity_top.png')
        bpy.ops.render.render(write_still=True)
    (folder / ("identity_metadata.json" if review else "preview_metadata.json")).write_text(
        json.dumps(
            {
                "status": "visual_preview_only_native_units_no_physics",
                "color_groups": groups,
                "exploded": False,
                "camera_and_colors": "visualization only",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
