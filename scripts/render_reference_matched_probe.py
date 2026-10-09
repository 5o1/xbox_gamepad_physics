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

arguments = sys.argv[sys.argv.index("--") + 1 :]
root = Path(__file__).resolve().parents[1]
requested_root = Path(arguments[0]).resolve()
candidate = Path(arguments[1])
hdri = Path(arguments[2])
hdri_records = {
    "boiler_room_4k.exr": {
        "slug": "boiler_room",
        "source_record": "references/boiler_room_hdri.json",
        "output_directory": "reference_matched_cycles_probe",
    },
    "industrial_workshop_foundry_4k.hdr": {
        "slug": "industrial_workshop_foundry",
        "source_record": "references/industrial_workshop_foundry_hdri.json",
        "output_directory": "reference_matched_cycles_industrial_workshop_foundry_probe",
    },
    "studio_small_08_4k.exr": {
        "slug": "studio_small_08",
        "source_record": "references/studio_small_08_hdri.json",
        "output_directory": "reference_matched_cycles_studio_small_08_probe",
    },
}
if hdri.name not in hdri_records:
    raise SystemExit(f"No reviewed source record for HDRI: {hdri.name}")
hdri_record = hdri_records[hdri.name]
scene_path = (
    candidate
    / "official_import_4.5.9_LTS"
    / "Xbox_One_S_BatonyRobson_MATERIAL_REVIEW_UNCALIBRATED.blend"
)
hdri_record_path = root / hdri_record["source_record"]
model_record_path = root / "references/xbox_one_s_material_validation.json"
scene_audit_path = root / "results/xbox_official_import_comparison/official_import_4.5.9_LTS/audit.json"
reference_record_path = root / "references/sketchfab_render_pipeline_audit.json"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


require(requested_root == root,
        f"Project evidence root must be {root}, not caller-supplied {requested_root}")
source_record = json.loads(hdri_record_path.read_text())
expected_hdri_hash = (
    source_record.get("downloaded_file", {}).get("sha256")
    or source_record.get("file", {}).get("sha256")
)
require(isinstance(expected_hdri_hash, str) and len(expected_hdri_hash) == 64,
        f"{hdri_record_path}: missing recorded SHA-256")
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

reference_record = json.loads(reference_record_path.read_text())
reference_artifacts = reference_record.get("captured_reference_artifacts", {})


def verified_reference_artifact(name):
    record = reference_artifacts.get(name, {})
    relative = record.get("path")
    expected = record.get("sha256")
    require(isinstance(relative, str) and isinstance(expected, str) and len(expected) == 64,
            f"{reference_record_path}: incomplete {name} artifact identity")
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file(),
            f"{reference_record_path}: missing or unsafe {name} artifact {relative!r}")
    actual = sha256(path)
    require(actual == expected,
            f"{path}: SHA-256 {actual} does not match {reference_record_path} ({expected})")
    return path, actual


runtime_path, runtime_hash = verified_reference_artifact("runtime")
reference_front_path, reference_front_hash = verified_reference_artifact("front")
runtime = json.loads(runtime_path.read_text())
captured_camera = runtime.get("camera", {})


def finite_vector(value, label):
    require(isinstance(value, list) and len(value) == 3,
            f"{runtime_path}: {label} must contain exactly three numbers")
    require(all(isinstance(item, (int, float)) and not isinstance(item, bool)
                and math.isfinite(item) for item in value),
            f"{runtime_path}: {label} must contain finite numbers")
    return value


position_values = finite_vector(captured_camera.get("position"), "camera.position")
target_values = finite_vector(captured_camera.get("target"), "camera.target")
captured_fov = runtime.get("fov")
require(isinstance(captured_fov, (int, float)) and not isinstance(captured_fov, bool)
        and math.isfinite(captured_fov) and 0 < captured_fov < 180,
        f"{runtime_path}: missing finite confirmed fov; recapture with the current Viewer harness before rendering new evidence")

import bpy
from mathutils import Vector

output = (
    candidate
    / "official_import_4.5.9_LTS"
    / hdri_record["output_directory"]
)
output.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=str(scene_path), use_scripts=False)
scene = bpy.context.scene

# Values returned by the hash-verified Viewer capture after pause()+seekTo(0),
# setFov(), and the end-of-camera-animation callback.
target = Vector(target_values)
position = Vector(position_values)
camera = scene.camera
camera.data.type = "PERSP"
camera.data.sensor_fit = "VERTICAL"
camera.data.angle = math.radians(captured_fov)
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
fov_token = format(float(captured_fov), ".12g").replace(".", "p")
for strength in strengths:
    lighting.inputs["Strength"].default_value = strength
    token = str(strength).replace(".", "p")
    path = output / f"{hdri_record['slug']}_vertical_fov{fov_token}_strength_{token}.png"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    renders.append({
        "strength": strength,
        "file": path.name,
        "artifact_availability": "tracked_representative" if strength == 1.0 else "rebuildable_ignored",
    })

manifest = {
    "purpose": "camera projection correction and licensed-lighting calibration probe",
    "source_scene": str(scene_path),
    "source_scene_sha256": actual_scene_hash,
    "source_scene_audit": str(scene_audit_path.relative_to(root)),
    "official_reference": str(reference_front_path.relative_to(root)),
    "official_reference_sha256": reference_front_hash,
    "official_runtime": str(runtime_path.relative_to(root)),
    "official_runtime_sha256": runtime_hash,
    "official_reference_record": str(reference_record_path.relative_to(root)),
    "camera": {
        "position": list(position),
        "target": list(target),
        "fov_degrees": captured_fov,
        "sensor_fit": "VERTICAL",
        "evidence": "Viewer API captured camera; WebGL perspective projection uses vertical FoV semantics",
    },
    "hdri": {
        "file": str(hdri),
        "sha256": actual_hdri_hash,
        "license": source_record["license"].get("spdx_like_label", source_record["license"].get("name")),
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
    "artifact_distribution": {
        "batch_renders_default": "rebuildable_ignored",
        "tracked_exception": "The strength 1.0 frame is retained as the review representative for each licensed HDRI.",
        "meaning": "Other probe images are generated evidence and are not promised in a clean Git clone; rebuild requires the hash-verified external scene and HDRI inputs.",
    },
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
