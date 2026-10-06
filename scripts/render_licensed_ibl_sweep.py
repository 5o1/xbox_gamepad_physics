"""Render a traceable HDRI-strength sweep with Blender Standard color output.

This is a legal visual approximation experiment.  Poly Haven Boiler Room is
CC0; it is not claimed to be Sketchfab's Industrial Room environment.  The
sweep avoids selecting a hand-tuned light strength before comparing results.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


arguments = sys.argv[sys.argv.index("--") + 1 :]
root = Path(arguments[0])
candidate = Path(arguments[1])
hdri = Path(arguments[2])
camera_distance = float(arguments[3]) if len(arguments) > 3 else 4.5
scene_path = candidate / "official_import_4.5.9_LTS" / "Xbox_One_S_BatonyRobson_MATERIAL_REVIEW_UNCALIBRATED.blend"
output_name = "licensed_ibl_sweep" if camera_distance == 4.5 else "licensed_ibl_aligned_sweep"
output = candidate / "official_import_4.5.9_LTS" / output_name
output.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=str(scene_path), use_scripts=False)
scene = bpy.context.scene

# Camera is the accepted official-viewer near-pole front camera.  Its 0.9-degree
# tilt is derived from the public 1.555089-radian pitch limit and avoids the
# undefined roll at an exact +Z pole.
target = Vector((-0.03751669638838028, 0.24024943525070927, -0.2933788650683066))
near_pole_position = Vector((-0.03751669638838028, 0.16956937112292542, 4.206066026086034))
position = target + (near_pole_position - target).normalized() * camera_distance
camera = scene.camera
camera.data.type = "PERSP"
camera.data.angle = math.radians(35)
camera.location = position
camera.rotation_euler = (target - position).to_track_quat("-Z", "Y").to_euler()

# The source viewer disables analytic lights.  Remove the prior diagnostic AREA
# light before introducing the single environment-light variable.
disabled_lights = []
for obj in scene.objects:
    if obj.type == "LIGHT":
        obj.hide_render = True
        disabled_lights.append(obj.name)

world = bpy.data.worlds.get("Licensed IBL diagnostic") or bpy.data.worlds.new("Licensed IBL diagnostic")
world.use_nodes = True
scene.world = world
nodes = world.node_tree.nodes
links = world.node_tree.links
nodes.clear()

environment = nodes.new("ShaderNodeTexEnvironment")
environment.name = "CC0 Boiler Room 4K EXR"
environment.image = bpy.data.images.load(str(hdri), check_existing=False)
environment.interpolation = "Linear"

lighting = nodes.new("ShaderNodeBackground")
lighting.name = "Environment lighting strength (sweep variable)"
links.new(environment.outputs["Color"], lighting.inputs["Color"])

# Camera rays use a measured neutral approximation to the public viewer's dark
# background.  This background does not illuminate the object.  Two 300x300
# unobstructed reference crops had mean sRGB 0.106978 and 0.107470; their mean
# 0.107224 converts to scene-linear 0.0111807.
camera_background = nodes.new("ShaderNodeBackground")
camera_background.name = "Measured neutral display background approximation"
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

# Unitless powers of two form a calibration sweep.  They are test points, not
# inferred physical values for this unrelated HDRI.
strengths = (0.25, 0.5, 1.0, 2.0)
renders = []
for strength in strengths:
    lighting.inputs["Strength"].default_value = strength
    token = str(strength).replace(".", "p")
    path = output / f"boiler_room_standard_strength_{token}.png"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    renders.append({"strength": strength, "file": path.name})

manifest = {
    "purpose": "licensed environment-light and Standard-view diagnostic sweep",
    "source_scene": str(scene_path),
    "hdri": {
        "file": str(hdri),
        "sha256": "8b4c9147603de5aa166046845104a019e339da9b450d54c8d9786ae5758e32f7",
        "license": "CC0-1.0",
        "source_record": "sources/boiler_room_hdri.json",
        "blender_colorspace": environment.image.colorspace_settings.name,
    },
    "camera": {
        "position": list(position),
        "target": list(target),
        "distance": camera_distance,
        "vertical_fov_degrees": 35,
        "evidence": "official Viewer API camera harness; public pitch limit",
        "alignment_calibration": None if camera_distance == 4.5 else {
            "method": "same 1600x700+0+100 crop, grayscale threshold 35%, trimmed bright-shell width",
            "official_viewer_width_px": 896,
            "initial_blender_width_px": 1571,
            "initial_distance": 4.5,
            "formula": "4.5 * 1571 / 896",
            "derived_distance": 7.890066964285714,
            "status": "first-order projection calibration; final silhouette alignment still requires verification",
        },
    },
    "color_management": {
        "view_transform": "Standard",
        "look": "None",
        "exposure": 0,
        "gamma": 1,
        "rationale": "public Sketchfab settings have toneMapping.enable=false",
    },
    "disabled_analytic_lights": disabled_lights,
    "background": {
        "type": "non-lighting uniform approximation",
        "linear_rgb": [0.0111807, 0.0111807, 0.0111807],
        "measurement": "mean of two unobstructed 300x300 official-viewer crops; sRGB mean 0.107224",
    },
    "renders": renders,
    "held_fixed": [
        "source GLB geometry and official Blender 4.5 glTF material import",
        "camera",
        "Cycles samples and denoising",
        "Standard display transform",
        "HDRI and rotation",
    ],
    "changed": "World Background strength only",
    "limitations": [
        "Boiler Room is a licensed visual approximation, not Sketchfab Industrial Room.",
        "The sweep has not yet selected an accepted strength.",
        "The website AO, alpha two-pass behavior, bloom, SSR, and sharpen are not reproduced.",
        "The camera background is uniform and does not reproduce the clean_dark image gradient.",
    ],
    "acceptance_status": "diagnostic_only",
}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2))
