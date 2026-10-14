"""One persistent Blender/Cycles renderer; one JSON request per stdin line.

Start with the packaged approved .blend open. Render settings and materials
come from that scene; only part poses, camera and viewport size change.
"""
import base64
import json
import math
from pathlib import Path
import re
import sys
import tempfile

import bpy
from mathutils import Matrix, Quaternion

if bpy.app.version[:2] != (4, 5):
    raise RuntimeError("viewer requires Blender 4.5")

scene = bpy.context.scene
assert scene.render.engine == 'CYCLES'
assert scene.get('approved_reference_sha256') == '260187ba839674ce2ed49d5d37c3eeb5ca95206fccb7c13ce2655d7001204907'
scene.frame_set(0)
graph = bpy.context.evaluated_depsgraph_get()
originals = list(scene.objects)
helpers = {p.custom_shape for o in originals if o.type == 'ARMATURE' for p in o.pose.bones if p.custom_shape}
objects = sorted((o for o in originals if o.type == 'MESH' and o not in helpers), key=lambda o:o.name)
assert len(objects) == 16
parts = {}
for index, obj in enumerate(objects):
    evaluated = obj.evaluated_get(graph)
    mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=graph)
    transform = evaluated.matrix_world.copy()
    mesh.transform(transform)
    if transform.to_3x3().determinant() < 0:
        mesh.flip_normals()
    name = obj.name.split('_XBox Gamepad')[0]
    name = f'{index:02d}_{re.sub(r"[^a-zA-Z0-9_-]", "_", name)}_VISUAL_UNCALIBRATED'
    static = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(static)
    parts[name] = static
for obj in originals:
    if obj.type in ('MESH', 'ARMATURE'):
        bpy.data.objects.remove(obj, do_unlink=True)

prefs = bpy.context.preferences.addons['cycles'].preferences
try:
    prefs.compute_device_type = 'CUDA'
    prefs.get_devices()
    gpu = next((d for d in prefs.devices if d.type == 'CUDA'), None)
    for device in prefs.devices:
        device.use = device == gpu
    scene.cycles.device = 'GPU' if gpu else 'CPU'
except TypeError:
    scene.cycles.device = 'CPU'
scene.render.use_persistent_data = True
conversion = Matrix.Rotation(math.pi / 2, 4, 'X')
inverse_conversion = conversion.inverted()
camera = scene.camera
with tempfile.TemporaryDirectory(prefix='xgp-cycles-') as directory:
    scene.render.filepath = str(Path(directory) / 'frame.png')
    print('XGP_READY', flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            for name, values in request['parts'].items():
                # Browser part matrices are glTF Y-up, vertices in this scene Z-up.
                matrix = Matrix([values[i:i+4] for i in range(0, 16, 4)]).transposed()
                parts[name].matrix_world = conversion @ matrix @ inverse_conversion
            camera.location = request['camera']['position']
            x, y, z, w = request['camera']['quaternion']
            camera.rotation_mode = 'QUATERNION'
            camera.rotation_quaternion = Quaternion((w, x, y, z))
            camera.data.type = 'PERSP'
            camera.data.sensor_fit = 'VERTICAL'
            camera.data.angle = math.radians(request['camera']['fov'])
            scene.render.resolution_x, scene.render.resolution_y = request['size']
            bpy.ops.render.render(write_still=True)
            payload = base64.b64encode(Path(scene.render.filepath).read_bytes()).decode('ascii')
            print('XGP_FRAME ' + payload, flush=True)
        except Exception as error:
            print('XGP_ERROR ' + str(error), flush=True)
