"""Controlled diagnostics only; do not overwrite accepted materials or geometry."""
import bpy
import json
import sys
import numpy as np
from pathlib import Path
from mathutils import Vector
root=Path(sys.argv[sys.argv.index('--')+1]);out=root/'material_diagnostics';out.mkdir(exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(root/'xbox/xbox_one_s_controllergamepad_animated.glb'))
report={}
for current,original in [('Image_0','Gamepad_BaseColor_EasterEgges.png'),('Image_2','Gamepad_Emissive.png'),('Image_3','Gamepad_Normal.png')]:
    image=bpy.data.images[current]
    other=bpy.data.images.load(str(root/'fbx/textures'/original))
    other.colorspace_settings.name=image.colorspace_settings.name
    a=np.array(image.pixels[:]);b=np.array(other.pixels[:])
    report[original]={'glb_size':list(image.size),'original_size':list(other.size),'decoded_max_abs_diff':float(np.max(np.abs(a-b))) if a.shape==b.shape else None}
for image in bpy.data.images:
    if image.name=='Specular Tint':
        report['generated_specular_tint_nonfinite_pixels']=int(np.count_nonzero(~np.isfinite(np.array(image.pixels[:]))))
scene=bpy.context.scene;scene.frame_set(0)
graph=bpy.context.evaluated_depsgraph_get()
pts=[e.matrix_world@Vector(p) for o in scene.objects if o.type=='MESH' for e in [o.evaluated_get(graph)] for p in e.bound_box]
lo=Vector([min(p[i] for p in pts) for i in range(3)]);hi=Vector([max(p[i] for p in pts) for i in range(3)])
center=(lo+hi)/2;extent=max(hi-lo)
world=bpy.data.worlds.new('Controlled diagnostic world');world.use_nodes=True;scene.world=world
world.node_tree.nodes['Background'].inputs[0].default_value=(.35,.35,.35,1)
world.node_tree.nodes['Background'].inputs[1].default_value=.8
bpy.ops.object.camera_add(location=center+Vector((0,0,extent*3)))
cam=bpy.context.object;cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=extent*1.2;scene.camera=cam
scene.render.engine='CYCLES';scene.cycles.samples=32;scene.cycles.use_denoising=True
scene.render.resolution_x=900;scene.render.resolution_y=900;scene.render.resolution_percentage=100
def render(name):
    scene.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True)
render('01_glb_original_uniform_world')
world.node_tree.nodes['Background'].inputs[1].default_value=.2
bpy.ops.object.light_add(type='AREA',location=center+Vector((-extent,extent,extent*2)))
light=bpy.context.object;light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler();light.data.energy=250*extent**2;light.data.size=extent
render('02_glb_directional_light')
mat=next(m for m in bpy.data.materials if m.use_nodes and m.node_tree.nodes.get('Principled BSDF'))
tree=mat.node_tree;tree.nodes.clear();bsdf=tree.nodes.new('ShaderNodeBsdfPrincipled');output=tree.nodes.new('ShaderNodeOutputMaterial');tree.links.new(bsdf.outputs['BSDF'],output.inputs['Surface'])
bindings={}
for filename,socket,space in [('Gamepad_BaseColor_EasterEgges.png','Base Color','sRGB'),('Gamepad_Roughness.png','Roughness','Non-Color'),('Gamepad_Metallic.png','Metallic','Non-Color'),('Gamepad_Emissive.png','Emission','sRGB'),('Gamepad_Normal.png','Normal','Non-Color')]:
    tex=tree.nodes.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(root/'fbx/textures'/filename),check_existing=True);tex.image.colorspace_settings.name=space
    if socket=='Normal':
        normal=tree.nodes.new('ShaderNodeNormalMap');tree.links.new(tex.outputs['Color'],normal.inputs['Color']);tree.links.new(normal.outputs['Normal'],bsdf.inputs[socket])
    else:tree.links.new(tex.outputs['Color'],bsdf.inputs[socket])
    bindings[filename]=socket
bsdf.inputs['Emission Strength'].default_value=10
render('03_original_maps_same_directional_light')
for obj in list(scene.objects):
    if obj.type not in {'CAMERA','LIGHT'}:
        bpy.data.objects.remove(obj,do_unlink=True)
bpy.ops.import_scene.fbx(filepath=str(root/'fbx/source/Xbox Controller (Animated) by Batony Robson.fbx'))
scene.frame_set(1)
for obj in scene.objects:
    if obj.type=='MESH':
        obj.data.materials.clear();obj.data.materials.append(mat)
render('04_original_fbx_original_maps')
report['diagnostic_bindings']=bindings
report['caveats']=['Original map rebinding is a diagnostic, not a website material reconstruction.','AO not multiplied into base color. Original normal map handedness not yet established.','Directional light is a controlled comparison, not the website HDRI.','Variants 1-3 use GLB geometry/UV; variant 4 uses original FBX geometry/UV. All use Filmic.','Variant 3 has visibly mismatched UV and is NOT a corrected asset.']
(out/'comparison.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
