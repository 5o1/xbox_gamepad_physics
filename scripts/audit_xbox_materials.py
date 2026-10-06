"""Read imported GLB nodes and compare packed images with supplied glTF PNGs."""
import bpy
import hashlib
import json
import sys
from pathlib import Path
root = Path(sys.argv[sys.argv.index('--')+1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(root/'xbox/xbox_one_s_controllergamepad_animated.glb'))
materials=[]
for mat in bpy.data.materials:
    if not mat.use_nodes:
        continue
    nodes=[]
    for n in mat.node_tree.nodes:
        item={'name':n.name,'type':n.type}
        if n.type=='TEX_IMAGE':
            item.update(image=n.image.name,colorspace=n.image.colorspace_settings.name)
        if n.type=='BSDF_PRINCIPLED':
            item['inputs']={s.name: str(s.default_value) for s in n.inputs if hasattr(s,'default_value')}
        nodes.append(item)
    materials.append({'name':mat.name,'nodes':nodes,'links':[f'{l.from_node.name}.{l.from_socket.name} -> {l.to_node.name}.{l.to_socket.name}' for l in mat.node_tree.links]})
known={hashlib.sha256(p.read_bytes()).hexdigest():p.name for p in (root/'gltf/textures').glob('*') if p.is_file()}
images=[]
for i in bpy.data.images:
    digest=hashlib.sha256(i.packed_file.data).hexdigest() if i.packed_file else None
    images.append({'name':i.name,'sha256':digest,'matching_gltf_file':known.get(digest),'size':list(i.size)})
report={'materials':materials,'images':images,'default_view_transform':bpy.context.scene.view_settings.view_transform}
(root/'review/material_audit.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
