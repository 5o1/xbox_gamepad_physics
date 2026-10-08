"""Package the user-selected Cycles recipe, without changing the old scene.

blender -b original.blend --python this.py -- preset.json boiler_room.exr output.blend [render.png]
World node setup is the existing render_reference_matched_probe.py recipe.
"""
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

preset_path, hdri, destination, *render = map(Path, sys.argv[sys.argv.index('--') + 1:])
preset = json.loads(preset_path.read_text())
assert hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest() == preset['source_scene_sha256']
assert hashlib.sha256(hdri.read_bytes()).hexdigest() == preset['hdri_sha256']
scene = bpy.context.scene
camera = scene.camera
camera.data.type = 'PERSP'
camera.data.sensor_fit = preset['camera']['sensor_fit']
camera.data.angle = math.radians(preset['camera']['fov_degrees'])
camera.location = preset['camera']['position']
camera.rotation_euler = (Vector(preset['camera']['target']) - camera.location).to_track_quat('-Z', 'Y').to_euler()
for obj in scene.objects:
    if obj.type == 'LIGHT':
        obj.hide_render = True
world = bpy.data.worlds.new('User-approved Boiler Room')
world.use_nodes = True
scene.world = world
nodes, links = world.node_tree.nodes, world.node_tree.links
nodes.clear()
environment = nodes.new('ShaderNodeTexEnvironment')
environment.image = bpy.data.images.load(str(hdri), check_existing=False)
environment.interpolation = 'Linear'
lighting = nodes.new('ShaderNodeBackground')
lighting.inputs['Strength'].default_value = preset['environment_strength']
links.new(environment.outputs['Color'], lighting.inputs['Color'])
camera_background = nodes.new('ShaderNodeBackground')
camera_background.inputs['Color'].default_value = (*preset['camera_background_linear'], 1)
camera_background.inputs['Strength'].default_value = 1
light_path = nodes.new('ShaderNodeLightPath')
mix = nodes.new('ShaderNodeMixShader')
output = nodes.new('ShaderNodeOutputWorld')
links.new(light_path.outputs['Is Camera Ray'], mix.inputs[0])
links.new(lighting.outputs[0], mix.inputs[1])
links.new(camera_background.outputs[0], mix.inputs[2])
links.new(mix.outputs[0], output.inputs['Surface'])
scene.render.engine = preset['renderer']
scene.cycles.samples = preset['samples']
scene.cycles.use_denoising = preset['denoising']
scene.render.resolution_x, scene.render.resolution_y = preset['resolution']
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.image_settings.color_depth = '8'
for name, value in preset['color_management'].items():
    setattr(scene.view_settings, name, value)
scene['approved_reference_sha256'] = preset['reference_sha256']
bpy.ops.file.pack_all()
destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(destination), compress=True)
if render:
    # Choose the first visible GPU; CUDA_VISIBLE_DEVICES scopes it externally.
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'CUDA'
    prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type == 'CUDA'
    scene.cycles.device = 'GPU'
    scene.render.filepath = str(render[0])
    bpy.ops.render.render(write_still=True)
