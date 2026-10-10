"""Render unchanged STL geometry from six orthographic directions for identity review.

Camera framing and clay shading are display choices, not physical parameters.
No remeshing, repair, inferred assembly transforms or missing-part fabrication.
"""
import hashlib
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

source, output = map(Path, sys.argv[sys.argv.index('--') + 1:])
output.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.import_mesh.stl(filepath=str(source))
objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
points = [o.matrix_world @ Vector(p) for o in objects for p in o.bound_box]
low = Vector([min(p[i] for p in points) for i in range(3)])
high = Vector([max(p[i] for p in points) for i in range(3)])
center, extent = (low + high) / 2, max(high - low)
scene = bpy.context.scene
bpy.ops.object.camera_add()
camera = bpy.context.object
camera.data.type = 'ORTHO'
camera.data.ortho_scale = extent * 1.2
camera.data.clip_end = extent * 10
scene.camera = camera
scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'SINGLE'
scene.display.shading.single_color = (0.55, 0.58, 0.62)
scene.display.shading.show_cavity = True
scene.display.shading.background_type = 'WORLD'
scene.world.color = (0.06, 0.06, 0.06)
scene.render.resolution_x = 1000
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
for name, direction in [('pos_x',(1,0,0)),('neg_x',(-1,0,0)),('pos_y',(0,1,0)),('neg_y',(0,-1,0)),('pos_z',(0,0,1)),('neg_z',(0,0,-1))]:
    camera.location = center + Vector(direction) * extent * 3
    camera.rotation_euler = (center-camera.location).to_track_quat('-Z','Y').to_euler()
    if name == 'pos_z':
        camera.rotation_euler.rotate_axis('Z', math.pi)
    scene.render.filepath = str(output / (name+'.png'))
    bpy.ops.render.render(write_still=True)
(output/'render_manifest.json').write_text(json.dumps({
    'source': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'bounds_native_units': [list(low),list(high)],
    'objects': [{'name':o.name,'faces':len(o.data.polygons),'vertices':len(o.data.vertices)} for o in objects],
    'geometry_modified': False, 'physical_scale_verified': False,
    'user_approved': False, 'camera_views': 'six axis-aligned orthographic views; +Z rolled 180 degrees for upright Wesk Front.stl front view',
    'material': 'neutral clay override; not original texture'
},indent=2))
