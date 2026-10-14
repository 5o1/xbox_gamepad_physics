"""Export existing static geometry and original PBR material for simulators.

No mesh reduction, UV edits, rescaling or physical parameter creation.
The scalar maps separate glTF G=roughness and B=metallic for SAPIEN's R-channel inputs.
"""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import struct

from PIL import Image

from .build_kinematics import build as build_kinematics

from .paths import DATA_ROOT, ROOT


def read_glb(path):
    data=path.read_bytes()
    magic,version,size=struct.unpack_from('<III',data)
    assert magic==0x46546C67 and version==2 and size==len(data)
    length,kind=struct.unpack_from('<II',data,12)
    assert kind==0x4E4F534A
    document=json.loads(data[20:20+length])
    binary_length,binary_kind=struct.unpack_from('<II',data,20+length)
    assert binary_kind==0x004E4942
    return document,data[28+length:28+length+binary_length]


DEFAULT_OUTPUT = ROOT/'build/standalone/common/xbox_one_s/visual'


def build(output: Path = DEFAULT_OUTPUT, *, kinematics: Path | None = None, inputs: Path = ROOT):
    source=inputs/'assets/xbox_one_s/source/xbox_one_s_controllergamepad_animated.glb'
    static=inputs/'assets/xbox_one_s/visual/Xbox_One_S_BatonyRobson_STATIC_VISUAL_UNCALIBRATED.glb'
    inventory=json.loads((inputs/'assets/xbox_one_s/visual/inventory.json').read_text())
    inventory_by_stem={Path(item['file']).stem:item for item in inventory['objects']}
    profile=json.loads(kinematics.read_text()) if kinematics is not None else build_kinematics(inputs=inputs)[1]
    assert hashlib.sha256(source.read_bytes()).hexdigest()==profile['source_bindings']['source_glb_sha256']
    assert hashlib.sha256(static.read_bytes()).hexdigest()==profile['visual']['sha256']
    authored,authored_bin=read_glb(source)
    geometry,geometry_bin=read_glb(static)
    output.mkdir(parents=True,exist_ok=True)
    textures=output/'textures';textures.mkdir(exist_ok=True)
    material=authored['materials'][0]
    names=['base_color','metallic_roughness','emissive','normal','specular_intensity']
    texture_files=[]
    for index,image in enumerate(authored['images']):
        view=authored['bufferViews'][image['bufferView']]
        start=view.get('byteOffset',0)
        data=authored_bin[start:start+view['byteLength']]
        filename=f'textures/{names[index]}.png'
        (output/filename).write_bytes(data)
        im=Image.open(io.BytesIO(data))
        assert im.size==(2048,2048)
        texture_files.append({'file':filename,'sha256':hashlib.sha256(data).hexdigest(),'size':list(im.size)})
    combined=Image.open(output/'textures/metallic_roughness.png')
    for name,channel in [('roughness','G'),('metallic','B'),('occlusion','R')]:
        combined.getchannel(channel).save(textures/f'{name}.png')
    specular_alpha=Image.open(textures/'specular_intensity.png').convert('RGBA').getchannel('A')
    specular_alpha.save(textures/'specular_factor.png')
    indices=set()
    for mesh in geometry['meshes']:
        for primitive in mesh['primitives']:
            indices.update(primitive['attributes'].values());indices.add(primitive['indices'])
            assert {'POSITION','NORMAL','TEXCOORD_0'}<=primitive['attributes'].keys()
            assert primitive.get('mode',4)==4
    buffer_indices={geometry['accessors'][index]['bufferView'] for index in indices}
    packed=bytearray();views={}
    for index in sorted(buffer_indices):
        old=geometry['bufferViews'][index]
        while len(packed)%4:packed.append(0)
        offset=len(packed);start=old.get('byteOffset',0)
        packed.extend(geometry_bin[start:start+old['byteLength']])
        views[index]={**old,'buffer':0,'byteOffset':offset}
    (output/'meshes.bin').write_bytes(packed)
    view_order=sorted(views)
    view_map={old:index for index,old in enumerate(view_order)}
    accessors=copy.deepcopy(geometry['accessors'])
    for accessor in accessors:
        assert 'sparse' not in accessor
        accessor['bufferView']=view_map[accessor['bufferView']]
    parts=[]
    for node in geometry['nodes']:
        if 'mesh' not in node:continue
        assert not any(key in node for key in ('matrix','translation','rotation','scale'))
        mesh=copy.deepcopy(geometry['meshes'][node['mesh']])
        for primitive in mesh['primitives']:primitive.pop('material',None)
        document={
            'asset':{'version':'2.0','generator':'Xbox One S simulator visual export'},
            'buffers':[{'uri':'meshes.bin','byteLength':len(packed)}],
            'bufferViews':[views[index] for index in view_order],
            'accessors':accessors,
            'meshes':[mesh],'nodes':[{'mesh':0,'name':node['name']}],
            'scenes':[{'nodes':[0]}],'scene':0,
        }
        filename=node['name']+'.gltf'
        source_record=inventory_by_stem[node['name']]
        (output/filename).write_text(json.dumps(document,separators=(',',':'))+'\n')
        primitive=mesh['primitives'][0]
        parts.append({'name':node['name'],'file':filename,
                      'source_name':source_record['name'],
                      'source_object':source_record['source_object'],
                      'source_matrix_world':source_record['source_matrix_world'],
                      'vertices':geometry['accessors'][primitive['attributes']['POSITION']]['count'],
                      'triangles':geometry['accessors'][primitive['indices']]['count']//3})
    assert len(parts)==16
    manifest={
        'asset_id':'xbox_one_s','stage':'visual','dynamics_ready':False,
        'source_sha256':profile['source_bindings']['source_glb_sha256'],
        'geometry_sha256':profile['visual']['sha256'],
        'coordinate_frame':'gltf_y_up','meters_per_native_unit':profile['visual']['meters_per_native_unit'],
        'blender_source_to_simulation_rotation_x_rad':profile['visual']['gltf_to_viewer_rotation_x_rad'],
        'scale_status':'existing width-fit visual estimate; not measured local geometry',
        'parts':parts,'source_material':material,'source_textures':texture_files,
        'sapien_material':{
            'base_color':[1,1,1,1],'emission':[1,1,1,10],'roughness':1,'metallic':1,
            'specular':.5,'ior':1.5,
            'textures':{'base_color_texture':'textures/base_color.png','emission_texture':'textures/emissive.png',
                        'normal_texture':'textures/normal.png','roughness_texture':'textures/roughness.png',
                        'metallic_texture':'textures/metallic.png'},
            'limitations':['Authored specular-alpha texture is preserved. SAPIEN has a scalar specular slot only; 0.5 represents dielectric F0=0.04, and spatial variation needs visual review.',
                           'Authored occlusion texture is preserved but this SAPIEN material API has no AO texture slot.'],
            'authored_specular_alpha_range':list(specular_alpha.getextrema()),
        },
        'license':'CC-BY-4.0','author':'BatonyRobson',
        'source_url':'https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4',
        'changes':'Geometry/UV/normals copied from existing static bake. Original material/images restored. Scalar channels separated without changing their values.',
    }
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'parts':len(parts),'textures':len(texture_files),'mesh_bytes':len(packed),'output':str(output)}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    build(args.output)


if __name__=='__main__':main()
