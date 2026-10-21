"""Inspect the Xbox One S in SAPIEN, optionally using RoboTwin's scene factory.

python examples/robotwin_visual.py --robotwin-root /path/to/RoboTwin --output /tmp/xgp-sapien
Add --interactive to open SAPIEN's native Viewer. No robot or contact dynamics are created.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image
import sapien
from transforms3d.quaternions import mat2quat

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from xbox_gamepad_physics.robotwin import load_visual_into_scene


def look_at(position,target):
    forward=np.asarray(target)-np.asarray(position);forward/=np.linalg.norm(forward)
    left=np.cross([0,0,1],forward);left/=np.linalg.norm(left)
    up=np.cross(forward,left)
    return sapien.Pose(p=position,q=mat2quat(np.column_stack([forward,left,up])))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robotwin-root',type=Path)
    parser.add_argument('--environment',type=Path)
    parser.add_argument('--table-scene',action='store_true',help='Use RoboTwin table, wall, default lights and ALOHA head-camera pose')
    parser.add_argument('--table-color',type=float,nargs=3,default=[.24,.28,.32],metavar=('R','G','B'))
    parser.add_argument('--output',type=Path,default=Path('/tmp/xgp-sapien-visual'))
    parser.add_argument('--interactive',action='store_true')
    parser.add_argument('--spp',type=int,default=32,help='RoboTwin RT samples per pixel for this inspection run')
    args=parser.parse_args()
    args.output=args.output.resolve()
    if args.environment:args.environment=args.environment.resolve()
    if args.robotwin_root:
        platform=args.robotwin_root.resolve()
        sys.path.insert(0,str(platform))
        os.chdir(platform)  # RoboTwin's own import-time asset lookup is CWD-relative.
        from envs._base_task import Base_Task, create_box, create_table
        task=Base_Task();task.render_freq=0;task.random_light=False
        sapien.render.set_ray_tracing_samples_per_pixel(args.spp)
        if args.environment:
            task.setup_scene(ambient_light=[0,0,0],direction_lights=[],point_lights=[])
        else:
            task.setup_scene()
        if args.table_scene:
            task.table_z_bias=0;task.random_background=False;task.eval_mode=False
            task.wall=create_box(task.scene,sapien.Pose(p=[0,1,1.5]),half_size=[3,.6,1.5],
                                 color=(1,.9,.9),name='wall',is_static=True)
            task.table=create_table(task.scene,sapien.Pose(p=[0,0,.74]),length=1.2,width=.7,
                                     height=.74,thickness=.05,color=tuple(args.table_color),
                                     name='table',is_static=True)
        scene=task.scene;owner='RoboTwin Base_Task.setup_scene'
    else:
        sapien.render.set_camera_shader_dir('rt')
        sapien.render.set_ray_tracing_samples_per_pixel(args.spp)
        sapien.render.set_ray_tracing_path_depth(8)
        sapien.render.set_ray_tracing_denoiser('oidn')
        scene=sapien.Scene([sapien.render.RenderSystem('cuda:0')])
        owner='SAPIEN Scene'
    if args.environment:
        scene.set_environment_map(str(args.environment.resolve()))
    elif not args.robotwin_root:
        scene.set_ambient_light([.5,.5,.5])
        scene.add_directional_light([0,.5,-1],[.5,.5,.5],shadow=True)
    root=sapien.Pose(p=[0,0,.8 if args.table_scene else .8])
    visual=load_visual_into_scene(scene,root)
    camera=scene.add_camera('xbox_reference',1600,900,math.radians(37 if args.table_scene else 35),.001,10)
    scale=visual.manifest['meters_per_native_unit']
    base=np.asarray(root.p)
    target=base+scale*np.array([-.037516698,.24024944,-.29337886])
    positions={
        'front':base+scale*np.array([-.037516698,-.55975056,4.20662117]),
        'oblique':base+scale*np.array([2,-3,3.5]),
        'side':base+scale*np.array([4.6,0,.5]),
        'back':base+scale*np.array([0,-.8,-4.5]),
    }
    if args.table_scene:
        head_position=np.array([-.032,-.45,1.35])
        head_target=head_position+np.array([0,.6,-.8])
        positions={'head_camera':head_position,'front_camera':np.array([0,-.45,.85]),
                   'review_oblique':np.array([.45,-.55,1.15])}
        target=head_target
    args.output.mkdir(parents=True,exist_ok=True)
    records=[]
    for name,position in positions.items():
        camera.entity.set_pose(look_at(position,target));scene.update_render()
        started=time.perf_counter();camera.take_picture()
        rgba=camera.get_picture('Color')
        elapsed=time.perf_counter()-started
        if args.table_scene:
            rgb=rgba[...,:3]
        else:
            # Preserve native alpha output, and display the camera background used
            # by the approved reference. Environment radiance still lights the model.
            background=.107
            rgb=rgba[...,:3]*rgba[...,3:4]+background*(1-rgba[...,3:4])
        Image.fromarray(np.rint(np.clip(rgb,0,1)*255).astype(np.uint8)).save(args.output/f'{name}.png')
        records.append({'view':name,'seconds':elapsed,'finite':bool(np.isfinite(rgba).all())})
    timings=[]
    for angle in np.linspace(-.4,.4,20):
        position=base+scale*np.array([4.4*math.sin(angle),-1,4.4*math.cos(angle)])
        camera.entity.set_pose(look_at(position,target))
        started=time.perf_counter();scene.update_render();camera.take_picture();camera.get_picture('Color')
        timings.append(time.perf_counter()-started)
    report={'sapien_version':sapien.__version__,'scene_owner':owner,'parts':len(visual.entities),
            'render_only':all(len(entity.components)==1 for entity in visual.entities.values()),
            'captures':records,'orbit_frame_seconds':timings,
            'mean_orbit_fps':1/float(np.mean(timings)),'material_limitations':visual.manifest['sapien_material']['limitations']}
    report['samples_per_pixel']=args.spp
    report['table_scene']=args.table_scene
    report['table_color']=args.table_color if args.table_scene else None
    report['lighting']='RoboTwin defaults' if args.table_scene else ('environment map' if args.environment else 'standalone defaults')
    (args.output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    if args.interactive:
        from sapien.utils import Viewer
        viewer=Viewer(shader_dir='rt',resolutions=(1600,900))
        viewer.set_scene(scene)
        pose=look_at(positions['front'],target)
        viewer.window.set_camera_parameters(.001,10,math.radians(35))
        viewer.window.set_camera_pose(pose)
        while not viewer.closed:
            scene.update_render();viewer.render()


if __name__=='__main__':main()
