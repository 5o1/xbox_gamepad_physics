"""Run in Blender with the saved review scene open; export its display settings.

Usage: blender -b saved.blend --python this.py -- output_directory
The scene is read only. No lights, materials or view settings are tuned here.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

import bpy

output = Path(sys.argv[sys.argv.index('--') + 1])
output.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
scene_path = Path(bpy.data.filepath)
background = next(n for n in scene.world.node_tree.nodes if n.type == 'BACKGROUND')
color_root = Path(bpy.utils.system_resource('DATAFILES')) / 'colormanagement'
record = {
    'source_scene': scene_path.name,
    'source_scene_sha256': hashlib.sha256(scene_path.read_bytes()).hexdigest(),
    'blender_version': bpy.app.version_string,
    'engine': scene.render.engine,
    'color': {'view': scene.view_settings.view_transform, 'look': scene.view_settings.look,
              'exposure': scene.view_settings.exposure, 'gamma': scene.view_settings.gamma},
    'world': {'color_linear': list(background.inputs['Color'].default_value)[:3],
              'strength': background.inputs['Strength'].default_value},
    'lights': [],
    'lut_sha256': {},
}
for obj in scene.objects:
    if obj.type != 'LIGHT':
        continue
    light = obj.data
    if light.type != 'AREA' or light.shape not in ('SQUARE', 'RECTANGLE'):
        raise ValueError(f'Unsupported saved light: {obj.name}')
    record['lights'].append({
        'name': obj.name, 'type': light.type, 'shape': light.shape,
        'position': list(obj.matrix_world.translation),
        'quaternion_xyzw': list(obj.matrix_world.to_quaternion())[1:] + [obj.matrix_world.to_quaternion().w],
        'color_linear': list(light.color), 'power': light.energy,
        'width': light.size, 'height': light.size_y if light.shape == 'RECTANGLE' else light.size,
    })
for name in ('filmic_desat_33.cube', 'filmic_to_0-70_1-03.spi1d'):
    source = color_root / 'filmic' / name
    shutil.copyfile(source, output / name)
    record['lut_sha256'][name] = hashlib.sha256(source.read_bytes()).hexdigest()
shutil.copyfile(color_root / 'config.ocio', output / 'blender_config.ocio')
(output / 'settings.json').write_text(json.dumps(record, indent=2) + '\n')
# Independent color samples through Blender's own display transform.
samples = [[v, v, v] for v in (0, .01, .07, .18, .5, 1, 4, 16)] + [[4,.1,.1],[.1,4,.1],[.1,.1,4],[10,2,.2]]
image = bpy.data.images.new('Filmic verification', width=len(samples), height=1, float_buffer=True)
image.pixels = [v for rgb in samples for v in (*rgb, 1)]
image.save_render(str(output / 'blender_color_samples.png'), scene=scene)
(output / 'color_samples.json').write_text(json.dumps(samples) + '\n')
print(json.dumps(record))
