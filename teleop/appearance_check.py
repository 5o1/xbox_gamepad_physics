"""Native RoboTwin URDF versus derived visual meshes and material evidence."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def run(args):
    import cv2
    import numpy as np
    import sapien
    from experiments.scene import look_at, create_render_scene
    from .gripper import ASSET_URDF,LINKS,JOINTS,derive_urdf,parse_builder
    from experiments.runner import load_config
    from .site import resolve_config
    cfg=resolve_config(load_config('configs/teleop_gripper.yaml'))['teleop']
    cfg=dict(cfg,attach_visual=True)
    args.output=args.output.resolve()
    args.output.mkdir(parents=True,exist_ok=True)
    source=Path(cfg['robotwin_root'])/ASSET_URDF
    scene_cfg={'robotwin_root': cfg['robotwin_root'], 'timestep': .004}
    settings={'shader': args.shader, 'samples_per_pixel': args.spp, 'denoiser': 'oidn'}
    native=create_render_scene(scene_cfg, **settings)
    loader=native.create_urdf_loader();loader.fix_root_link=True
    full=loader.load(str(source))
    q=np.zeros(full.dof)
    for i,joint in enumerate(full.get_active_joints()):
        if joint.name in JOINTS:q[i]=.02
    full.set_qpos(q)
    derived_scene=create_render_scene(scene_cfg, **settings)
    builder=parse_builder(derived_scene,derive_urdf(cfg['robotwin_root'],args.output/'derived'),True,cfg)
    derived=builder.build();derived.set_qpos([.02,.02])
    def body(link):return link.entity.find_component_by_type(sapien.render.RenderBodyComponent)
    def materials(component):
        result=[]
        for shape in component.render_shapes:
            for part in shape.parts:
                m=part.material;t=m.base_color_texture
                result.append({'filename':shape.filename,'scale':shape.scale.tolist(),
                    'vertices':len(part.vertices),'triangles':len(part.triangles),
                    'base_color':list(m.base_color),'metallic':m.metallic,'roughness':m.roughness,'specular':m.specular,
                    'texture':None if t is None else {'filename':t.filename,'size':[t.width,t.height],
                        'is_srgb':t.is_srgb,'pixel_min':float(t.download().min()),'pixel_max':float(t.download().max())}})
        return result
    result={'source_urdf':str(source),'shader':args.shader,'links':{},'dae':{}}
    reference_root=full.find_link_by_name('fl_link6').entity_pose
    # Clone just the selected native visuals into the same raster scene, at the
    # same relative poses as the derived subtree. No collision geometry is used.
    scene=create_render_scene(scene_cfg, **settings)
    entities=[]
    for offset,art in ((-.09,full),(.09,derived)):
        for name in LINKS:
            link=art.find_link_by_name(name);component=body(link)
            e=sapien.Entity();clone=sapien.render.RenderBodyComponent()
            for shape in component.render_shapes:clone.attach(shape.clone())
            e.add_component(clone)
            pose=reference_root.inv()*link.entity_pose if art is full else derived.get_root_pose().inv()*link.entity_pose
            pose.p+=np.array([0,offset,0])
            e.set_pose(pose);scene.add_entity(e);entities.append(e)
    for name in LINKS:
        left=body(full.find_link_by_name(name));right=body(derived.find_link_by_name(name))
        lm,rm=materials(left),materials(right)
        same=all(np.array_equal(a.vertices,b.vertices) and np.array_equal(a.triangles,b.triangles)
            for sa,sb in zip(left.render_shapes,right.render_shapes) for a,b in zip(sa.parts,sb.parts))
        result['links'][name]={'native':lm,'derived':rm,'records':[
            {'filename':v.filename,'type':v.type} for lb in builder.link_builders if lb.name==name for v in lb.visual_records],
            'vertices_and_indices_equal':same,'materials_equal':lm==rm}
        path=source.parent/f'aloha_maniskill_sim/meshes/link{name[-1]}.dae'
        n={'c':'http://www.collada.org/2005/11/COLLADASchema'};tree=ET.parse(path)
        textures=[]
        for item in tree.findall('.//c:library_images/c:image/c:init_from',n):
            png=path.parent/item.text;pixels=cv2.imread(str(png),cv2.IMREAD_UNCHANGED)
            textures.append({'path':str(png),'shape':list(pixels.shape),'mean_channels':pixels.mean(axis=(0,1)).tolist(),
                             'min':int(pixels.min()),'max':int(pixels.max())})
        result['dae'][name]={'path':str(path),'textures':textures}
    camera=scene.add_camera('comparison',1280,720,np.deg2rad(45),.001,3)
    camera.entity.set_pose(look_at([.34,-.34,.23],[.06,0,0]))
    scene.update_render();camera.take_picture();pixels=camera.get_picture('Color')
    rgb=cv2.cvtColor(cv2.convertScaleAbs(pixels,alpha=255),cv2.COLOR_RGBA2RGB)
    cv2.imwrite(str(args.output/'native_vs_derived.png'),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
    (args.output/'appearance.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--shader',choices=['default','rt'],default='default')
    p.add_argument('--spp',type=int,default=4)
    run(p.parse_args())
