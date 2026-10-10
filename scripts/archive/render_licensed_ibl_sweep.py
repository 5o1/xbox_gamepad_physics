"""Render a traceable HDRI-strength sweep with Blender Standard color output.

This is a legal visual approximation experiment.  Poly Haven Boiler Room is
CC0; it is not claimed to be Sketchfab's Industrial Room environment.  The
sweep avoids selecting a hand-tuned light strength before comparing results.
"""

import hashlib
import json
import math
import sys
from pathlib import Path

arguments = sys.argv[sys.argv.index("--") + 1 :]
root = Path(__file__).resolve().parents[2]
hdri_record_path = root / "references/boiler_room_hdri.json"
model_record_path = root / "references/xbox_one_s_material_validation.json"
scene_audit_path = root / "build/experiments/xbox_official_import_comparison/official_import_4.5.9_LTS/audit.json"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


require(
    len(arguments) in (3, 4),
    "usage: blender --background --python render_licensed_ibl_sweep.py -- "
    "PROJECT_ROOT CANDIDATE_DIR HDRI "
    "[historical_near_pole|historical_near_pole_width_scaled]",
)
requested_root = Path(arguments[0]).resolve()
candidate = Path(arguments[1])
hdri = Path(arguments[2])
scene_path = candidate / "official_import_4.5.9_LTS" / "Xbox_One_S_BatonyRobson_MATERIAL_REVIEW_UNCALIBRATED.blend"
camera_mode = arguments[3] if len(arguments) == 4 else "historical_near_pole"
camera_modes = {
    "historical_near_pole": {
        "distance": 4.5,
        "output_name": "licensed_ibl_sweep",
        "alignment_calibration": None,
    },
    "historical_near_pole_width_scaled": {
        "distance": 7.890066964285714,
        "output_name": "licensed_ibl_aligned_sweep",
        "alignment_calibration": {
            "method": "same 1600x700+0+100 crop, grayscale threshold 35%, trimmed bright-shell width",
            "official_viewer_width_px": 896,
            "initial_blender_width_px": 1571,
            "initial_distance": 4.5,
            "formula": "4.5 * 1571 / 896",
            "derived_distance": 7.890066964285714,
            "status": "historical distance calculation from the rejected horizontal-FoV setup; retained only as a diagnostic input and not an alignment calibration",
        },
    },
}
require(
    camera_mode in camera_modes,
    f"unknown camera mode {camera_mode!r}; choose one of {sorted(camera_modes)}",
)
camera_configuration = camera_modes[camera_mode]
camera_distance = camera_configuration["distance"]

require(requested_root == root,
        f"Project evidence root must be {root}, not caller-supplied {requested_root}")
hdri_record = json.loads(hdri_record_path.read_text())
expected_hdri_hash = hdri_record.get("downloaded_file", {}).get("sha256")
require(isinstance(expected_hdri_hash, str) and len(expected_hdri_hash) == 64,
        f"{hdri_record_path}: missing downloaded_file.sha256")
actual_hdri_hash = sha256(hdri)
require(actual_hdri_hash == expected_hdri_hash,
        f"{hdri}: SHA-256 {actual_hdri_hash} does not match {hdri_record_path} ({expected_hdri_hash})")

model_record = json.loads(model_record_path.read_text())
expected_model_hash = model_record.get("source_glb_sha256")
require(isinstance(expected_model_hash, str) and len(expected_model_hash) == 64,
        f"{model_record_path}: missing source_glb_sha256")
scene_audit = json.loads(scene_audit_path.read_text())
require(scene_audit.get("checks", {}).get("source_hash") == expected_model_hash,
        f"version-controlled {scene_audit_path}: source model hash does not match {model_record_path}")
expected_scene_hash = scene_audit.get("source_scene_sha256")
require(isinstance(expected_scene_hash, str) and len(expected_scene_hash) == 64,
        f"{scene_audit_path}: missing source_scene_sha256; rerun check_gltf_import_versions.py")
actual_scene_hash = sha256(scene_path)
require(actual_scene_hash == expected_scene_hash,
        f"{scene_path}: SHA-256 {actual_scene_hash} does not match version-controlled {scene_audit_path} ({expected_scene_hash})")

import bpy
from mathutils import Vector

output_name = camera_configuration["output_name"]
output = candidate / "official_import_4.5.9_LTS" / output_name
output.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=str(scene_path), use_scripts=False)
scene = bpy.context.scene

# This is a retained historical near-pole diagnostic, not the accepted viewer
# camera.  Later browser validation found that its 0.9-degree tilt leaves roll
# numerically unstable; viewer/sketchfab_reference.html therefore uses a
# visibly tilted y=-0.8, z=+4.5 camera instead.
target = Vector((-0.03751669638838028, 0.24024943525070927, -0.2933788650683066))
near_pole_position = Vector((-0.03751669638838028, 0.16956937112292542, 4.206066026086034))
position = target + (near_pole_position - target).normalized() * camera_distance
camera = scene.camera
camera.data.type = "PERSP"
camera.data.sensor_fit = "VERTICAL"
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
    renders.append({
        "strength": strength,
        "file": path.name,
        "artifact_availability": "rebuildable_ignored",
    })

manifest = {
    "purpose": "licensed environment-light and Standard-view diagnostic sweep",
    "source_scene": str(scene_path),
    "source_scene_sha256": actual_scene_hash,
    "source_scene_audit": str(scene_audit_path.relative_to(root)),
    "hdri": {
        "file": str(hdri),
        "sha256": actual_hdri_hash,
        "license": hdri_record["license"]["spdx_like_label"],
        "source_record": "references/boiler_room_hdri.json",
        "blender_colorspace": environment.image.colorspace_settings.name,
    },
    "camera": {
        "position": list(position),
        "target": list(target),
        "distance": camera_distance,
        "vertical_fov_degrees": 35,
        "sensor_fit": "VERTICAL",
        "evidence": "historical near-pole diagnostic derived from the public pitch limit; rejected by the later browser harness because roll was numerically unstable",
        "mode": camera_mode,
        "alignment_calibration": camera_configuration["alignment_calibration"],
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
    "artifact_distribution": {
        "batch_renders_default": "rebuildable_ignored",
        "meaning": "Sweep images are generated evidence and are not promised in a clean Git clone; rebuild requires the hash-verified external scene and HDRI inputs.",
    },
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
