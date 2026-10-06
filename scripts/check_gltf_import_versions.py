"""Compare official glTF importers without editing source geometry/materials.

Evidence: Sketchfab blender-plugin README known-issues; Khronos glTF 4.5
pbrMetallicRoughness.py specular() connects texture alpha * 0.5 to IOR Level.
Render controls below are diagnostic studio settings, not inferred asset data.
"""
import bpy
import hashlib
import json
import struct
import sys
from pathlib import Path
from mathutils import Vector

root=Path(sys.argv[sys.argv.index('--')+1])
source=root/'xbox/xbox_one_s_controllergamepad_animated.glb'
data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
assert digest=='5c5671c83a9cf15db4b8399e7010aa7d5cde915687ceb348b583eb00b0ed24e2'
gltf=json.loads(data[20:20+struct.unpack_from('<I',data,12)[0]])
out=root/('official_import_'+bpy.app.version_string.replace(' ','_'));out.mkdir(exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
scene=bpy.context.scene;scene.frame_set(0)
mat=next(m for m in bpy.data.materials if m.use_nodes and any(n.type=='BSDF_PRINCIPLED' for n in m.node_tree.nodes))
bsdf=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
def upstream(socket,seen=None):
    seen=set() if seen is None else seen
    images=[]
    for link in socket.links:
        node=link.from_node
        if node.name in seen:continue
        seen.add(node.name)
        if node.type=='TEX_IMAGE':images.append({'image':node.image.name,'colorspace':node.image.colorspace_settings.name,'output':link.from_socket.name})
        for s in node.inputs:images.extend(upstream(s,seen))
    return images
channels={name:upstream(bsdf.inputs[name]) for name in ['Base Color','Alpha','Normal','Roughness','Metallic']}
specular_key='Specular IOR Level' if 'Specular IOR Level' in bsdf.inputs else 'Specular'
channels[specular_key]=upstream(bsdf.inputs[specular_key])
custom_shapes={p.custom_shape for o in scene.objects if o.type=='ARMATURE' for p in o.pose.bones if p.custom_shape}
helpers=[o for o in scene.objects if o.type=='MESH' and o in custom_shapes]
assert all(any(c.hide_render for c in o.users_collection) or o.hide_render for o in helpers), 'Bone helper would enter render'
mesh_objects=[o for o in scene.objects if o.type=='MESH' and o not in custom_shapes]
geometry_hash=hashlib.sha256()
for obj in sorted(mesh_objects,key=lambda o:o.name):
    geometry_hash.update(obj.name.encode())
    for vertex in obj.data.vertices:geometry_hash.update(struct.pack('<3f',*vertex.co))
    for poly in obj.data.polygons:geometry_hash.update(struct.pack('<'+'I'*len(poly.vertices),*poly.vertices))
    for uv in obj.data.uv_layers:
        for item in uv.data:geometry_hash.update(struct.pack('<2f',*item.uv))
checks={'source_hash':digest,'mesh_count':len(mesh_objects),'vertex_color_layers':sum(len(o.data.color_attributes) for o in mesh_objects),'material_geometry_uv_edited':False,'shading_inputs':channels,'specular_texture_reaches_shader':bool(channels[specular_key]),'geometry_uv_hash':geometry_hash.hexdigest()}
print('IMPORT_CHECKS',json.dumps(checks))
assert checks['mesh_count']==16 and checks['vertex_color_layers']==0
assert all(channels[k] for k in ['Base Color','Alpha','Normal','Roughness','Metallic'])
if bpy.app.version>=(4,5,0):assert checks['specular_texture_reaches_shader']
report={'blender':bpy.app.version_string,'checks':checks,'source_material':gltf['materials'][0],
 'excluded_importer_bone_display_helpers':[o.name for o in helpers],
 'materials': [{'name':n.name,'type':n.type,'image':n.image.name if n.type=='TEX_IMAGE' else None} for n in mat.node_tree.nodes],
 'links':[f'{l.from_node.name}.{l.from_socket.name} -> {l.to_node.name}.{l.to_socket.name}' for l in mat.node_tree.links],
 'limitations':['Baked glTF AO is retained as metadata, not equivalent to Cycles ambient occlusion.','Studio lighting does not reproduce the website HDRI.','Matching website appearance is not yet accepted.']}
(out/'audit.json').write_text(json.dumps(report,indent=2))
graph=bpy.context.evaluated_depsgraph_get()
pts=[e.matrix_world@Vector(p) for obj in mesh_objects for e in [obj.evaluated_get(graph)] for p in e.bound_box]
lo=Vector([min(p[i] for p in pts) for i in range(3)]);hi=Vector([max(p[i] for p in pts) for i in range(3)])
center=(lo+hi)/2;extent=max(hi-lo)
world=bpy.data.worlds.new('Controlled studio');world.use_nodes=True;scene.world=world
world.node_tree.nodes['Background'].inputs[0].default_value=(.35,.35,.35,1)
world.node_tree.nodes['Background'].inputs[1].default_value=.2
bpy.ops.object.light_add(type='AREA',location=center+Vector((-extent,extent,extent*2)))
light=bpy.context.object;light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler();light.data.energy=250*extent**2;light.data.size=extent
bpy.ops.object.camera_add(location=center+Vector((0,0,extent*3)))
cam=bpy.context.object;cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=extent*1.2;scene.camera=cam
scene.render.engine='CYCLES';scene.cycles.samples=32;scene.cycles.use_denoising=True
scene.view_settings.view_transform='Filmic';scene.view_settings.look='None';scene.view_settings.exposure=0;scene.view_settings.gamma=1
scene.render.resolution_x=900;scene.render.resolution_y=900;scene.render.resolution_percentage=100
scene.render.filepath=str(out/'front.png');bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'Xbox_One_S_BatonyRobson_MATERIAL_REVIEW_UNCALIBRATED.blend'))
print(json.dumps(checks,indent=2))
