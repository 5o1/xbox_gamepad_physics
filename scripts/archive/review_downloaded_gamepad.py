"""Inspect user-supplied FBX/GLB; render original GLB materials, no geometry edits."""
import bpy
import json
import sys
from pathlib import Path
from mathutils import Vector

root = Path(sys.argv[sys.argv.index('--')+1])
out = root/'review'
out.mkdir(exist_ok=True)
report = {}
args = sys.argv[sys.argv.index('--')+1:]
inputs = [('fbx', Path(args[2])), ('glb', Path(args[1]))] if len(args) >= 3 else [('fbx', next((root/'fbx/source').glob('*.fbx'))), ('glb', root/'xbox/xbox_one_s_controllergamepad_animated.glb')]
for kind, path in inputs:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if kind == 'fbx':
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        bpy.ops.import_scene.gltf(filepath=str(path))
    report[kind] = {
        'file': str(path),
        'objects': [{'name':o.name,'type':o.type,'vertices':len(o.data.vertices) if o.type=='MESH' else None,'polygons':len(o.data.polygons) if o.type=='MESH' else None,'materials':[m.name for m in o.data.materials] if o.type=='MESH' else [],'bones':[b.name for b in o.data.bones] if o.type=='ARMATURE' else []} for o in bpy.context.scene.objects],
        'actions': [{'name':a.name,'frame_range':list(a.frame_range)} for a in bpy.data.actions],
        'images': [{'name':i.name,'size':list(i.size),'packed':bool(i.packed_file)} for i in bpy.data.images]
    }
    # Edge-connected components distinguish separate islands from a fused surface.
    for obj, entry in zip(bpy.context.scene.objects, report[kind]['objects']):
        if obj.type != 'MESH':
            continue
        parents = list(range(len(obj.data.vertices)))
        def find(i):
            while parents[i] != i:
                parents[i] = parents[parents[i]]
                i = parents[i]
            return i
        for edge in obj.data.edges:
            a, b = edge.vertices
            parents[find(a)] = find(b)
        counts = {}
        for i in range(len(parents)):
            key = find(i)
            counts[key] = counts.get(key, 0) + 1
        entry['edge_connected_components_vertices'] = sorted(counts.values(), reverse=True)
(out/'inventory.json').write_text(json.dumps(report,indent=2))
scene = bpy.context.scene
scene.frame_set(0)
depsgraph = bpy.context.evaluated_depsgraph_get()
points = [o.matrix_world@Vector(p) for obj in scene.objects if obj.type=='MESH' for o in [obj.evaluated_get(depsgraph)] for p in o.bound_box]
lo = Vector([min(p[i] for p in points) for i in range(3)])
hi = Vector([max(p[i] for p in points) for i in range(3)])
center, extent = (lo+hi)/2, max(hi-lo)
world = bpy.data.worlds.new('Review neutral studio')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (0.35,0.35,0.35,1)
world.node_tree.nodes['Background'].inputs[1].default_value = 0.8
scene.world = world
bpy.ops.object.camera_add()
cam = bpy.context.object
cam.data.type = 'ORTHO'
cam.data.ortho_scale = extent*1.2
cam.data.clip_start = extent*0.001
cam.data.clip_end = extent*20
scene.camera = cam
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.use_denoising = True
scene.render.resolution_x = 900
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
for name, direction in [('pos_x',(1,0,0)),('neg_x',(-1,0,0)),('pos_y',(0,1,0)),('neg_y',(0,-1,0)),('pos_z',(0,0,1)),('neg_z',(0,0,-1))]:
    cam.location = center+Vector(direction)*extent*3
    cam.rotation_euler = (center-cam.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath = str(out/(name+'.png'))
    bpy.ops.render.render(write_still=True)
(out/'render_settings.json').write_text(json.dumps({'frame':0,'bounds_native':[list(lo),list(hi)],'geometry_modified':False,'materials':'original GLB materials','views':'six orthographic directions','physical_scale_verified':False,'user_approved':False},indent=2))
