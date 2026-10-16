"""B1 native review. All application, scene and stepping lifetime lives here."""
import argparse
import importlib.metadata
import json
import math
import os
from pathlib import Path

from isaaclab.app import AppLauncher
parser=argparse.ArgumentParser()
parser.add_argument('--resources',type=Path,required=True)
parser.add_argument('--binding',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--root-mode',choices=['fixed','free'],default='fixed')
parser.add_argument('--render-mode',choices=['RaytracedLighting','PathTracing'])
parser.add_argument('--camera-plan',type=Path)
parser.add_argument('--hdr',type=Path,default=os.environ.get('XGP_I2_HDR'))
AppLauncher.add_app_launcher_args(parser)
args=parser.parse_args()
launcher=AppLauncher(args,**({'renderer':args.render_mode} if args.render_mode else {}))
app=launcher.app

import numpy as np
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.backends.common.appearance import load_appearance
from xbox_gamepad_physics.backends.common.collision import load_collision_sources
from xbox_gamepad_physics.backends.common.physical import load_physical
from xbox_gamepad_physics.isaac import build_usd,make_articulation_cfg,bind_articulation
from xbox_gamepad_physics.isaac.diagnostics import readback_usd,readback_articulation

common=args.resources/'common/xbox_one_s'
motion=motion_from_dict(json.loads((common/'motion/full_controls.json').read_text()))
physical=load_physical(resource_directory=common/'physical')
appearance=load_appearance(directory=common/'visual',binding=json.loads(args.binding.read_text()))
collisions=load_collision_sources(directory=common/'collision')
args.output.mkdir(parents=True,exist_ok=True)
tag=args.render_mode or args.root_mode
result={'root_mode':args.root_mode,'render_mode':args.render_mode,
    'versions':{x:importlib.metadata.version(x) for x in ['isaaclab','isaacsim','torch']}}
def save():
    (args.output/(tag+'_result.json')).write_text(json.dumps(result,indent=2)+'\n')
artifact=build_usd(args.output/(tag+'.usda'),motion=motion,physical=physical,
    appearance=appearance,collision_sources=collisions,visual_directory=common/'visual',root_mode=args.root_mode)
result['usd']=readback_usd(artifact,motion=motion,physical=physical,appearance=appearance,collision_sources=collisions)
save()
if not args.render_mode:
    import torch
    from isaaclab.sim import SimulationContext,SimulationCfg
    from isaaclab.assets import Articulation
    dt=.004
    sim=SimulationContext(SimulationCfg(dt=dt,device=args.device,gravity=(0.,0.,0.),log_dir=str(args.output/'lab_logs')))
    native=Articulation(make_articulation_cfg(artifact.usd_path,motion=motion,physical=physical))
    sim.reset()
    native.update(dt)
    handle=bind_articulation(native,motion=motion,physical=physical)
    result['native']=readback_articulation(native,motion=motion,physical=physical)
    assert handle.root_fixed==(args.root_mode=='fixed')
    q0=handle.joint_positions()
    targets={j.name:j.lower+.65*(j.upper-j.lower) for j in motion.joints}
    for name,value in targets.items():handle.set_joint_target(name,value)
    trace=[]
    for step in range(100):
        native.write_data_to_sim();sim.step(render=False);native.update(dt)
        if step%10==0:trace.append({'step':step+1,'q':handle.joint_positions()})
    q1=handle.joint_positions()
    response={j.name:abs(q1[j.name]-q0[j.name])/(j.upper-j.lower) for j in motion.joints}
    result['drive']={'initial':q0,'final':q1,'targets':targets,'normalized_response':response,'trace':trace,
        'gravity_m_s2':[0,0,0],'gravity_basis':'B1 isolated drive response fixture; not a physical gravity calibration'}
    save()
    assert all(v>.05 for v in response.values()),response
    handle.restore_passive_targets()
    for _ in range(100):
        native.write_data_to_sim();sim.step(render=False);native.update(dt)
    result['return_q']=handle.joint_positions()
    result['signals']=list(handle.gamepad_state().values)
    if not handle.root_fixed:
        pose0=native.data.root_pos_w.clone()
        velocity=torch.zeros((1,6),device=native.device);velocity[:,0]=.01
        native.write_root_velocity_to_sim(velocity)
        for _ in range(10):
            native.write_data_to_sim();sim.step(render=False);native.update(dt)
        delta=(native.data.root_pos_w-pose0).detach().cpu().tolist()[0]
        result['free_translation_m']=delta
        assert delta[0]>.0001,delta
    result['status']='passed';save()
else:
    import carb
    import omni.usd
    import omni.replicator.core as rep
    from pxr import UsdGeom,UsdLux,Gf
    from PIL import Image
    if not args.camera_plan or not args.hdr or not args.hdr.is_file():
        raise ValueError('render review requires the frozen D2 camera plan and approved HDR')
    plan=json.loads(args.camera_plan.read_text())
    omni.usd.get_context().new_stage()
    stage=omni.usd.get_context().get_stage()
    UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,'Z')
    stage.DefinePrim('/World/Gamepad','Xform').GetReferences().AddReference(str(artifact.usd_path))
    dome=UsdLux.DomeLight.Define(stage,'/World/BoilerRoom')
    dome.CreateTextureFileAttr(str(args.hdr));dome.CreateTextureFormatAttr('latlong')
    dome.CreateIntensityAttr(2000.);dome.CreateExposureAttr(0.);dome.OrientToStageUpAxis()
    camera=UsdGeom.Camera.Define(stage,'/World/Camera')
    camera.CreateFocalLengthAttr(35.);camera.CreateClippingRangeAttr(Gf.Vec2f(.001,10.))
    camera_op=camera.AddTransformOp()
    settings=carb.settings.get_settings()
    chosen={'/rtx/rendermode':args.render_mode,'/rtx/post/aa/op':3,
        '/rtx/translucency/enabled':True,'/rtx/raytracing/fractionalCutoutOpacity':True,
        '/rtx/pathtracing/fractionalCutoutOpacity':True,'/rtx/pathtracing/spp':8,
        '/rtx/pathtracing/totalSpp':64,'/rtx/pathtracing/maxBounces':8,
        '/rtx/pathtracing/optixDenoiser/enabled':True,'/rtx/indirectDiffuse/enabled':True,
        '/rtx/reflections/enabled':True,'/rtx/sceneDb/ambientLightIntensity':0.,
        '/rtx/material/omniRtxEnableOpacityOverride':False,'/rtx/multiGpu/enabled':False,
        '/rtx/material/translucencyAsOpacity':False,'/rtx/sceneDb/translucencyAsOpacity':False}
    result['render']={'captures':[],'hdr':'<APPROVED_BOILER_ROOM_HDR>',
        'dome_intensity':2000.,'radiometric_calibration':False,
        'intensity_basis':'Same B1b explicit rounded independent neutral-sphere unit approximation; no ABXY fitting',
        'display':'HdrColor linear RGB converted once to standard sRGB; no fitted gain'}
    for view in ['full','abxy']:
        v=plan['views'][view];w,h=v['resolution']
        aperture=70*math.tan(math.radians(v['fovy_degrees'])/2)
        camera.CreateVerticalApertureAttr(aperture);camera.CreateHorizontalApertureAttr(aperture*w/h)
        camera_op.Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*v['position_m']),Gf.Vec3d(*v['target_m']),Gf.Vec3d(0,0,1)).GetInverse())
        product=rep.create.render_product('/World/Camera',(w,h))
        annotator=rep.AnnotatorRegistry.get_annotator('HdrColor',device='cpu');annotator.attach([product])
        app.update()
        for k,value in chosen.items():settings.set(k,value)
        for _ in range(24):app.update()
        raw=annotator.get_data()
        assert isinstance(raw,np.ndarray) and raw.shape==(h,w,4) and np.isfinite(raw).all()
        linear=np.maximum(raw[...,:3].astype(np.float32),0)
        rgb=np.where(linear<=.0031308,12.92*linear,1.055*linear**(1/2.4)-.055)
        filename=tag+'_'+view+'.png'
        Image.fromarray(np.rint(np.clip(rgb,0,1)*255).astype(np.uint8)).save(args.output/filename)
        result['render']['captures'].append({'view':view,'file':filename,'camera':v,
            'settings':{k:settings.get(k) for k in chosen},'linear_rgb_minmax':[float(linear.min()),float(linear.max())]})
        save()
        print("CAPTURE "+filename,flush=True)
    result['status']='passed';save()
print('B1_DONE '+tag,flush=True)
app.close(skip_cleanup=True)
