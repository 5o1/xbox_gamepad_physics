"""Render one linear image and save it through two display transforms.

This is a rendering-pipeline ablation, not a website reproduction.  Geometry,
materials, camera, world, lights, samples, and the linear render result are held
fixed.  Only Blender's display transform changes between the two PNG files.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


root = Path(sys.argv[sys.argv.index("--") + 1])
comparison = root / "official_import_4.5.9_LTS"
scene_path = comparison / "Xbox_One_S_BatonyRobson_MATERIAL_REVIEW_UNCALIBRATED.blend"
settings_path = root / "review" / "public_viewer_settings.json"

bpy.ops.wm.open_mainfile(filepath=str(scene_path), use_scripts=False)
settings = json.loads(settings_path.read_text())
scene = bpy.context.scene

# Match the public viewer camera only.  Its coordinate registration remains an
# explicit open item; this experiment needs only one camera held fixed.
camera_settings = settings["options"]["camera"]
camera = scene.camera
camera.data.type = "PERSP"
camera.data.angle = math.radians(camera_settings["fov"])
camera.location = Vector(camera_settings["position"])
camera.rotation_euler = (
    Vector(camera_settings["target"]) - camera.location
).to_track_quat("-Z", "Y").to_euler()

scene.render.engine = "CYCLES"
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.color_depth = "8"

# Render once in scene-linear space.  save_render applies each selected display
# transform to the same Render Result, so lighting noise cannot confound the
# comparison.
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.view_settings.exposure = 0
scene.view_settings.gamma = 1
bpy.ops.render.render()

outputs = []
for transform, look, filename in (
    ("Filmic", "None", "source_camera_same_light_filmic.png"),
    ("Standard", "None", "source_camera_same_light_standard.png"),
):
    scene.view_settings.view_transform = transform
    scene.view_settings.look = look
    path = comparison / filename
    bpy.data.images["Render Result"].save_render(filepath=str(path), scene=scene)
    outputs.append(
        {
            "file": filename,
            "view_transform": transform,
            "look": look,
            "exposure": scene.view_settings.exposure,
            "gamma": scene.view_settings.gamma,
        }
    )

manifest = {
    "purpose": "single-variable display-transform ablation",
    "held_fixed": [
        "same scene-linear Render Result",
        "source GLB and imported materials",
        "camera",
        "world and area light",
        "Cycles render settings",
    ],
    "changed": "Blender view transform only; Look remains None",
    "linear_render_samples": scene.cycles.samples,
    "outputs": outputs,
    "important_limitations": [
        "The studio world and area light are not Sketchfab's Industrial Room IBL.",
        "Standard is a diagnostic approximation to a no-tone-mapping display path, not a claim of pixel equivalence.",
        "Sketchfab AO, SSR, bloom, and sharpen are not reproduced.",
        "Public camera coordinate registration is not yet independently verified.",
    ],
    "website_evidence": {
        "tone_mapping_enable": settings["options"]["scene"]["postProcess"]["toneMapping"]["enable"],
        "environment": settings["options"]["environment"],
        "lighting_enable": settings["options"]["lighting"]["enable"],
    },
}
(comparison / "color_management_ablation.json").write_text(
    json.dumps(manifest, indent=2) + "\n"
)
print(json.dumps(manifest, indent=2))
