"""Render a traceable Blender probe using the captured Viewer API camera.

This probe corrects an earlier projection mistake: the Sketchfab/WebGL camera
FoV is treated as vertical for the 16:9 screenshot, while Blender's default
landscape camera interprets ``Camera.angle`` through horizontal sensor fit.
The prior distance multiplier therefore compensated for a projection mismatch
instead of reproducing the source camera.

Lighting remains an explicitly labelled CC0 approximation.  The output must
not be described as an exact Sketchfab renderer reproduction.
"""

import json
import hashlib
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


arguments = sys.argv[sys.argv.index("--") + 1 :]
root = Path(arguments[0])
candidate = Path(arguments[1])
hdri = Path(arguments[2])
hdri_records = {
    "boiler_room_4k.exr": {
        "slug": "boiler_room",
        "source_record": "sources/boiler_room_hdri.json",
    },
    "industrial_workshop_foundry_4k.hdr": {
        "slug": "industrial_workshop_foundry",
        "source_record": "sources/industrial_workshop_foundry_hdri.json",
    },
    "studio_small_08_4k.exr": {
        "slug": "studio_small_08",
        "source_record": "sources/studio_small_08_hdri.json",
    },
}
if hdri.name not in hdri_records:
    raise SystemExit(f"No reviewed source record for HDRI: {hdri.name}")
hdri_record = hdri_records[hdri.name]
output = (
    candidate
    / "official_import_4.5.9_LTS"
    / f"reference_matched_cycles_{hdri_record['slug']}_probe"
)
output.mkdir(parents=True, exist_ok=True)

scene_path = (
    candidate
    / "official_import_4.5.9_LTS"
    / "Xbox_One_S_BatonyRobson_MATERIAL_REVIEW_UNCALIBRATED.blend"
)
bpy.ops.wm.open_mainfile(filepath=str(scene_path), use_scripts=False)
scene = bpy.context.scene

# Values returned by getCameraLookAt() after pause()+seekTo(0), setFov(35), and
# the end-of-camera-animation callback.  See
# results/xbox_sketchfab_viewer_reference/runtime.json.
target = Vector((-0.03751669638838028, 0.24024943525070927, -0.2933788650683066))
position = Vector((-0.03751669638838109, -0.5597505647492922, 4.206621134931694))
camera = scene.camera
camera.data.type = "PERSP"
camera.data.sensor_fit = "VERTICAL"
camera.data.angle = math.radians(35)
camera.location = position
camera.rotation_euler = (target - position).to_track_quat("-Z", "Y").to_euler()

disabled_lights = []
for obj in scene.objects:
    if obj.type == "LIGHT":
        obj.hide_render = True
        disabled_lights.append(obj.name)

world = bpy.data.worlds.get("Reference-matched licensed IBL probe") or bpy.data.worlds.new(
    "Reference-matched licensed IBL probe"
)
world.use_nodes = True
scene.world = world
nodes = world.node_tree.nodes
links = world.node_tree.links
nodes.clear()

environment = nodes.new("ShaderNodeTexEnvironment")
environment.name = "CC0 environment (not Sketchfab Industrial Room)"
environment.image = bpy.data.images.load(str(hdri), check_existing=False)
environment.interpolation = "Linear"

lighting = nodes.new("ShaderNodeBackground")
lighting.name = "Licensed environment-light strength"
links.new(environment.outputs["Color"], lighting.inputs["Color"])

# A neutral constant is deliberately kept separate from lighting.  It is only
# a placeholder for the official viewer's clean_dark radial background.
camera_background = nodes.new("ShaderNodeBackground")
camera_background.name = "Measured neutral background placeholder"
camera_background.inputs["Color"].default_value = (0.0111807, 0.0111807, 0.0111807, 1)
camera_background.inputs["Strength"].default_value = 1
light_path = nodes.new("ShaderNodeLightPath")
mix = nodes.new("ShaderNodeMixShader")
output_node = nodes.new("ShaderNodeOutputWorld")
links.new(light_path.outputs["Is Camera Ray"], mix.inputs[0])
links.new(lighting.outputs[0], mix.inputs[1])
links.new(camera_background.outputs[0], mix.inputs[2])
links.new(mix.outputs[0], output_node.inputs["Surface"])

scene.render.engine = "CYCLES"
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.color_depth = "8"
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.view_settings.exposure = 0
scene.view_settings.gamma = 1

# These are calibration probes, not inferred physical brightness values.
strengths = (0.5, 0.625, 0.75, 0.875, 1.0)
renders = []
for strength in strengths:
    lighting.inputs["Strength"].default_value = strength
    token = str(strength).replace(".", "p")
    path = output / f"{hdri_record['slug']}_vertical_fov35_strength_{token}.png"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    renders.append({"strength": strength, "file": path.name})

manifest = {
    "purpose": "camera projection correction and licensed-lighting calibration probe",
    "source_scene": str(scene_path),
    "official_reference": "results/xbox_sketchfab_viewer_reference/front.png",
    "official_runtime": "results/xbox_sketchfab_viewer_reference/runtime.json",
    "camera": {
        "position": list(position),
        "target": list(target),
        "fov_degrees": 35,
        "sensor_fit": "VERTICAL",
        "evidence": "Viewer API captured camera; WebGL perspective projection uses vertical FoV semantics",
    },
    "hdri": {
        "file": str(hdri),
        "sha256": hashlib.sha256(hdri.read_bytes()).hexdigest(),
        "license": "CC0-1.0",
        "source_record": hdri_record["source_record"],
        "role": "lighting approximation only; not Sketchfab Industrial Room",
    },
    "renderer": scene.render.engine,
    "color_management": {
        "view_transform": "Standard",
        "look": "None",
        "exposure": 0,
        "gamma": 1,
    },
    "disabled_analytic_lights": disabled_lights,
    "renders": renders,
    "acceptance_status": "probe_only",
    "known_unmatched_components": [
        "Industrial Room environment map and its preprocessing",
        "clean_dark radial background",
        "AO/specular occlusion semantics",
        "SSR, TAA, bloom, and sharpen",
        "Sketchfab production BRDF details",
    ],
}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2))
