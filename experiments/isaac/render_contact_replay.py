"""Render archived Isaac acceptance states as synchronized three-view videos.

USD transforms reproduce recorded joint coordinates and probe poses. The Kit
 timeline stays stopped: there are no physics steps, new contacts or new scores.
Contact overlays show the per-link aggregate points actually retained in traces.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time
from isaaclab.app import AppLauncher

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--archive',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--case',action='append',dest='cases')
p.add_argument('--result-dir',action='append',dest='result_dirs',
 help='Explicit result directory beneath archive/output; repeat to select a complete archive generation.')
p.add_argument('--source-label',default='Archived')
p.add_argument('--preview',action='store_true')
p.add_argument('--fps',type=int,default=30)
p.add_argument('--speed',type=float,default=.5)
p.add_argument('--orthographic',action='store_true',help='Equal-scale front/top/right views of the same controller.')
p.add_argument('--overlay-dir',type=Path,help='Existing canonical32 SVG overlay frames, indexed identically to this replay.')
AppLauncher.add_app_launcher_args(p)
a=p.parse_args();launcher=AppLauncher(a,renderer='RaytracedLighting');app=launcher.app
import numpy as np
import carb
import omni.usd
import omni.timeline
import omni.replicator.core as rep
from pxr import Usd,UsdGeom,UsdLux,UsdShade,Sdf,Gf,Tf
from PIL import Image,ImageDraw,ImageFont
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.backends.common.model import Pose
from xbox_gamepad_physics.backends.common.transforms import compose,rotate
from tests.acceptance import load_suite
from tests.acceptance.scoring import target_value


def link_poses(motion,q,root):
    poses={'controller_body':Pose(tuple(root[:3]),tuple(root[3:]))}
    pending=list(motion.joints)
    while pending:
        ready=[joint for joint in pending if joint.parent in poses]
        if not ready:raise ValueError('disconnected motion chain')
        for joint in ready:
            frame=compose(poses[joint.parent],Pose(joint.origin,joint.origin_orientation_wxyz))
            value=q[joint.name]
            if joint.kind=='prismatic':
                delta=Pose(tuple(value*x for x in joint.axis))
            else:
                norm=math.sqrt(sum(x*x for x in joint.axis))
                delta=Pose(orientation_wxyz=(math.cos(value/2),*(math.sin(value/2)*x/norm for x in joint.axis)))
            poses[joint.child]=compose(frame,delta);pending.remove(joint)
    return poses


def material(stage,path,color,opacity=1.):
    mat=UsdShade.Material.Define(stage,path)
    surf=UsdShade.Shader.Define(stage,path+'/Surface');surf.CreateIdAttr('UsdPreviewSurface')
    surf.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    surf.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.6)
    surf.CreateInput('opacity',Sdf.ValueTypeNames.Float).Set(opacity)
    surf.CreateInput('opacityThreshold',Sdf.ValueTypeNames.Float).Set(0.)
    mat.CreateSurfaceOutput().ConnectToSource(surf.ConnectableAPI(),'surface')
    return mat


def projection(position,camera,width=640,height=480):
    forward=np.asarray(camera['target_m'])-camera['position_m'];forward/=np.linalg.norm(forward)
    right=np.cross(forward,camera['up']);right/=np.linalg.norm(right)
    vertical=np.cross(right,forward);relative=np.asarray(position)-camera['position_m'];depth=np.dot(relative,forward)
    if depth<=0:return None
    if camera.get('projection')=='orthographic':
        scale=height/camera['visible_height_m']
        return width/2+np.dot(relative,right)*scale,height/2-np.dot(relative,vertical)*scale
    focal=height/(2*math.tan(math.radians(camera['fovy_deg']/2)))
    return width/2+np.dot(relative,right)*focal/depth,height/2-np.dot(relative,vertical)*focal/depth


def main():
    a.output.mkdir(parents=True,exist_ok=True)
    suite=load_suite();motion=motion_from_dict(json.loads((a.archive/'resources/common/xbox_one_s/motion/full_controls.json').read_text()))
    summaries={};origins={}
    directories=a.result_dirs or ['b4_sdf_05','r4_sdf_09','r4_sdf_15','r4_sdf_21']
    for directory in directories:
        for result in json.loads((a.archive/'output'/directory/'result.json').read_text())['cases']:
            if result['case'] in summaries:raise ValueError('Duplicate case across selected result directories')
            summaries[result['case']]=result;origins[result['case']]=directory
    wanted=a.cases or [c.case_id for c in suite.cases]
    source_usd=a.archive/'output'/directories[0]/'controller.usda'
    omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage()
    UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,'Z')
    timeline=omni.timeline.get_timeline_interface();timeline.stop()
    # Separate all three axes: a side camera must not see a different view's
    # controller through the transparent collision meshes.
    offsets=[np.full(3,panel*.5) for panel in range(3)]
    models=[];ops=[];probes=[];side_shapes=[]
    red=material(stage,'/World/Looks/Probe',(.95,.08,.04))
    side_blue=material(stage,'/World/Looks/ShellBlue',(.3,.65,.95),.18)
    side_orange=material(stage,'/World/Looks/ContactOrange',(.95,.58,.12),.35)
    for panel in range(3):
        prefix=f'/World/View{panel}'
        root=UsdGeom.Xform.Define(stage,prefix);root.GetPrim().GetReferences().AddReference(str(source_usd))
        models.append(root)
        operations={}
        for link in ['controller_body']+[j.child for j in motion.joints]:
            prim=stage.GetPrimAtPath(prefix+'/Links/'+Tf.MakeValidIdentifier(link))
            xform=UsdGeom.Xformable(prim);xform.ClearXformOpOrder()
            operations[link]=xform.AddTransformOp(UsdGeom.XformOp.PrecisionDouble,'replay')
        ops.append(operations)
        for prim in Usd.PrimRange(root.GetPrim()):
            path=str(prim.GetPath())
            if prim.IsA(UsdGeom.Mesh) and '/Collision/' in path:
                if panel==2 and not a.orthographic:
                    mesh=UsdGeom.Mesh(prim);mesh.CreatePurposeAttr('default');mesh.CreateDoubleSidedAttr(True)
                    UsdShade.MaterialBindingAPI.Apply(prim).Bind(side_blue)
                    side_shapes.append((prim,path.split('/Links/')[1].split('/')[0]))
            if panel==2 and not a.orthographic and prim.IsA(UsdGeom.Mesh) and '/Visual/' in path:
                UsdGeom.Imageable(prim).MakeInvisible()
        sphere=UsdGeom.Sphere.Define(stage,prefix+'/ProbeReplay');sphere.CreateRadiusAttr(suite.settings['radius_m'])
        UsdShade.MaterialBindingAPI.Apply(sphere.GetPrim()).Bind(red)
        probes.append(sphere.AddTranslateOp())
    dome=UsdLux.DomeLight.Define(stage,'/World/ReplayDome');dome.CreateColorAttr(Gf.Vec3f(.8,.85,1.));dome.CreateIntensityAttr(300.)
    light=UsdLux.DistantLight.Define(stage,'/World/ReplayKey');light.CreateIntensityAttr(600.)
    light.AddRotateXYZOp().Set(Gf.Vec3f(-30.,-20.,30.))
    cameras=[];annotations=[];products=[]
    width,height,header,footer=640,480,92,240 if a.overlay_dir else 174
    camera_prims=[]
    for panel in range(3):
        cam=UsdGeom.Camera.Define(stage,f'/World/Camera{panel}');cam.CreateFocalLengthAttr(35.)
        if a.orthographic:cam.CreateProjectionAttr(UsdGeom.Tokens.orthographic)
        camera_prims.append(cam)
        aperture=70*math.tan(math.radians(16))
        cam.CreateVerticalApertureAttr(aperture);cam.CreateHorizontalApertureAttr(aperture*width/height)
        cam.CreateClippingRangeAttr(Gf.Vec2f(.0005,20.));camera_op=cam.AddTransformOp();cameras.append(camera_op)
        product=rep.create.render_product(str(cam.GetPath()),(width,height));products.append(product)
        annotator=rep.AnnotatorRegistry.get_annotator('HdrColor',device='cpu');annotator.attach([product]);annotations.append(annotator)
    settings=carb.settings.get_settings();app.update()
    render_settings={'/rtx/rendermode':'RaytracedLighting','/rtx/post/aa/op':0,
       '/rtx/translucency/enabled':True,'/rtx/raytracing/fractionalCutoutOpacity':True,
       '/rtx/reflections/enabled':True,'/rtx/indirectDiffuse/enabled':True,'/rtx/multiGpu/enabled':False,
       '/rtx/material/translucencyAsOpacity':False,'/rtx/sceneDb/translucencyAsOpacity':False}
    for key,value in render_settings.items():settings.set(key,value)
    fonts='/usr/share/fonts/'
    font=ImageFont.truetype(fonts+'truetype/dejavu/DejaVuSans.ttf',22)
    small=ImageFont.truetype(fonts+'truetype/dejavu/DejaVuSans.ttf',18)
    chinese=ImageFont.truetype(fonts+'opentype/noto/NotoSansCJK-Bold.ttc',32)
    manifest={'schema':'isaac-archived-contact-video-v1','collision':'sdf','spacing_mm':.5,
       'source_label':a.source_label,'source_result_directories':directories,
       'fps':a.fps,'playback_speed':a.speed,'panel_resolution':[width,height],
       'frame_resolution':[width*3,height+header+footer],'physics_steps':0,
       'mode':'Recorded joint coordinates and probe poses; USD kinematics only; Kit timeline stopped.',
       'contact_marker':'White-bordered red=controller-body shell; green=moving part. Recorded per-link aggregate locations, NOT all individual contact points.',
       'side_panel':'Translucent source triangle shells, not an extracted cooked SDF isosurface.',
       'render_settings':render_settings,'lighting':{'dome_intensity':300.,'key_intensity':600.,'radiometric_calibration':False},'cases':[]}
    manifest['camera_layout']='front_top_right_orthographic_equal_scale' if a.orthographic else 'legacy_contact_views'
    manifest['canonical32_overlay']=bool(a.overlay_dir)
    if a.orthographic:manifest['side_panel']='Controller appearance from the local +X camera; no collision-shell substitution.'
    manifest_path=a.output/('preview_manifest.json' if a.preview else 'video_manifest.json')
    for name in wanted:
        case=suite.case(name);directory=origins[name];trace=a.archive/'output'/directory/f'trace_{name}.jsonl'
        rows=[json.loads(line) for line in trace.open()];result=summaries[name]
        def set_row(row):
            poses=link_poses(motion,row['joint_positions'],row['root_pose'])
            for panel in range(3):
                for link,pose in poses.items():
                    transform=Gf.Matrix4d(1.)
                    transform.SetRotate(Gf.Quatd(pose.orientation_wxyz[0],Gf.Vec3d(*pose.orientation_wxyz[1:])))
                    transform.SetTranslateOnly(Gf.Vec3d(*(np.asarray(pose.position_m)+offsets[panel])))
                    ops[panel][link].Set(transform)
                probes[panel].Set(Gf.Vec3d(*(np.asarray(row['probe']['pose'][:3])+offsets[panel])))
        balls=np.asarray([row['probe']['pose'][:3] for row in rows])
        planned=np.asarray(case.plan['point_m'])
        probe_distances=np.linalg.norm(balls-planned,axis=1)
        escaped=bool(np.any(probe_distances>.06))
        set_row(rows[0])
        bounds_prim=stage.GetPrimAtPath('/World/View0/Links') if escaped else models[0].GetPrim()
        bbox=UsdGeom.BBoxCache(Usd.TimeCode.Default(),['default']).ComputeWorldBound(bounds_prim).ComputeAlignedRange()
        # The probe was added under the same view root; include the complete
        # archived trajectory so front framing also covers the withdrawal.
        low,high=np.array(bbox.GetMin()),np.array(bbox.GetMax());corners=np.asarray([[x,y,z] for x in [low[0],high[0]] for y in [low[1],high[1]] for z in [low[2],high[2]]])
        framing_balls=balls[probe_distances<=.06] if escaped else balls
        whole=np.concatenate([corners,framing_balls])
        close=np.concatenate([framing_balls,planned[None,:]])
        root_rotation=np.column_stack([rotate(rows[0]['root_pose'][3:],axis) for axis in [(1,0,0),(0,1,0),(0,0,1)]])
        side=-1. if case.plan['point_m'][0]<rows[0]['root_pose'][0] else 1.
        definitions=[('front',whole,[0,0,1],[0,1,0],.014),('top',close,[0,1,0],[0,0,1],.012),('side',close,[side,0,0],[0,0,1],.012)]
        if a.orthographic:
            definitions=[('front',whole,[0,0,1],[0,1,0],.014),('top',whole,[0,1,0],[0,0,1],.014),('right',whole,[1,0,0],[0,0,1],.014)]
            common_height=0.
            for _,bounds,direction,up,padding in definitions:
                direction=root_rotation@direction;up=root_rotation@up
                right=np.cross(-direction,up);vertical=np.cross(right,-direction)
                span=np.ptp(bounds@np.column_stack([right,vertical]),axis=0)
                common_height=max(common_height,span[1]+2*padding,(span[0]+2*padding)/(width/height),.045)
        descriptions=[]
        for panel,(label,bounds,direction,up,padding) in enumerate(definitions):
            direction=root_rotation@direction;up=root_rotation@up;right=np.cross(-direction,up);vertical=np.cross(right,-direction)
            span=np.ptp(bounds@np.column_stack([right,vertical]),axis=0)
            visible_height=max(span[1]+2*padding,(span[0]+2*padding)/(width/height),.045)
            if a.orthographic:visible_height=common_height
            distance=visible_height/(2*math.tan(math.radians(16)))+.035
            target=(bounds.min(0)+bounds.max(0))/2;position=target+direction*distance
            camera={'name':label,'position_m':position.tolist(),'target_m':target.tolist(),'up':up.tolist(),'fovy_deg':32}
            if a.orthographic:
                camera.update(projection='orthographic',visible_height_m=visible_height)
                camera_prims[panel].CreateVerticalApertureAttr(visible_height*10.)
                camera_prims[panel].CreateHorizontalApertureAttr(visible_height*10.*width/height)
            descriptions.append(camera)
            cameras[panel].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*(position+offsets[panel])),Gf.Vec3d(*(target+offsets[panel])),Gf.Vec3d(*up)).GetInverse())
            actual_axis=camera_prims[panel].ComputeLocalToWorldTransform(Usd.TimeCode.Default()).TransformDir(Gf.Vec3d(0.,0.,1.))
            assert np.allclose(actual_axis,direction,atol=1e-12,rtol=0.)
        contacted={c['link'] for row in rows for c in row['contacts']}
        for prim,link in side_shapes:UsdShade.MaterialBindingAPI.Apply(prim).Bind(side_orange if link in contacted else side_blue)
        for _ in range(16):app.update()
        duration=len(rows)*.004
        video_indices=[min(len(rows)-1,round(frame*a.speed/(a.fps*.004))) for frame in range(math.ceil(duration/a.speed*a.fps)+1)]
        if a.overlay_dir:
            overlay_record=json.loads((a.overlay_dir/name/'complete.json').read_text())
            assert overlay_record['sample_indices']==video_indices,'canonical32 overlay samples differ from physical replay'
        if a.preview:
            hold=[i for i,row in enumerate(rows) if row['probe']['phase']=='hold']
            least=min(hold,key=lambda i:target_value(case.plan,rows[i]['signals'],rows[i]['probe']['events']))
            indices=[video_indices[0],min(video_indices,key=lambda value:abs(value-least)),video_indices[-1]]
        else:
            indices=video_indices
        filename=name+'_three_views.mp4';encoder=None
        if not a.preview:
            encoder=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24',
              '-video_size',f'{width*3}x{height+header+footer}','-framerate',str(a.fps),'-i','-','-an','-c:v','libx264',
              '-threads','3','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(a.output/filename)],stdin=subprocess.PIPE)
        started=time.monotonic();counts={'aggregate_points':0,'missing_positions':0,'projected_per_panel':[0,0,0],'outside_panel_per_panel':[0,0,0]};probe_error=0.
        probe_outside=[0,0,0]
        for frame,index in enumerate(indices):
            row=rows[index];set_row(row)
            app.update();app.update();assert not timeline.is_playing(),'replay must not step dynamics'
            actual=UsdGeom.XformCache().GetLocalToWorldTransform(stage.GetPrimAtPath('/World/View0/ProbeReplay')).ExtractTranslation()
            probe_error=max(probe_error,float(np.max(np.abs(np.array(actual)-row['probe']['pose'][:3]))))
            canvas=Image.new('RGB',(width*3,height+header+footer),(20,25,34));draw=ImageDraw.Draw(canvas)
            color=(51,255,119) if result['physics_passed'] else (255,48,48)
            draw.text((18,4),f'{name} | Isaac SDF {a.source_label} | {"成功" if result["physics_passed"] else "失败"} | {a.speed:g}倍速',font=chinese,fill=color,anchor='lt')
            signal=target_value(case.plan,row['signals'],row['probe']['events'])
            draw.text((18,45),f't = {(row["step"]+1)*.004:.3f} s   {row["probe"]["phase"].upper():<10} signal = {signal:+.4f}   hold minimum = {result["target_min"]:+.4f} / required {result["target_threshold"]:.2f}',font=font,fill='white')
            points=[c for c in row['contacts'] if c['point_m'] is not None]
            counts['aggregate_points']+=len(points);counts['missing_positions']+=len(row['contacts'])-len(points)
            for panel,annotator in enumerate(annotations):
                raw=annotator.get_data();assert isinstance(raw,np.ndarray) and raw.shape==(height,width,4) and np.isfinite(raw).all()
                linear=np.maximum(raw[...,:3].astype(np.float32),0)
                rgb=np.where(linear<=.0031308,12.92*linear,1.055*linear**(1/2.4)-.055)
                image=Image.fromarray(np.rint(np.clip(rgb,0,1)*255).astype(np.uint8));overlay=ImageDraw.Draw(image)
                probe_xy=projection(row['probe']['pose'][:3],descriptions[panel])
                if probe_xy is None or not (0<=probe_xy[0]<width and 0<=probe_xy[1]<height):
                    probe_outside[panel]+=1
                    overlay.rectangle((8,8,width-8,40),fill=(20,25,34))
                    overlay.text((15,12),'PROBE OUT OF VIEW (recorded position)',font=small,fill=(255,210,60))
                    if probe_xy is not None:
                        direction=np.asarray(probe_xy)-[width/2,height/2]
                        scale=min((width/2-12)/max(abs(direction[0]),1e-12),(height/2-12)/max(abs(direction[1]),1e-12))
                        edge=np.array([width/2,height/2])+direction*min(1.,scale)
                        overlay.ellipse((edge[0]-5,edge[1]-5,edge[0]+5,edge[1]+5),fill=(255,210,60))
                for c in points:
                    xy=projection(c['point_m'],descriptions[panel])
                    if xy is None or not (0<=xy[0]<width and 0<=xy[1]<height):counts['outside_panel_per_panel'][panel]+=1;continue
                    counts['projected_per_panel'][panel]+=1;x,y=xy
                    tint=(255,40,70) if c['link']=='controller_body' else (40,255,110)
                    overlay.ellipse((x-5,y-5,x+5,y+5),fill='white');overlay.ellipse((x-4,y-4,x+4,y+4),fill=tint)
                canvas.paste(image,(panel*width,header))
                label=(['FRONT +Z','TOP +Y','RIGHT +X'] if a.orthographic else ['FRONT | full controller, straight on','TOP | fixed contact close-up','SIDE | translucent triangle shells'])[panel]
                draw.text((panel*width+12,header+height+8),label,font=small,fill=(200,225,250))
            for divider in [width,2*width]:draw.line((divider,header,divider,header+height),fill=(110,125,145),width=2)
            shell=sum(c['link']=='controller_body' for c in points);stop=row['probe']['termination']['reason'] if row['probe']['termination'] else 'not stopped yet'
            lines=[f'Aggregated contact locations: shell {shell}, moving parts {len(points)-shell} | Red/white: shell; green/white: part.',
              f'Stop: {stop} | force = {np.linalg.norm(row["probe"]["force_n"]):.2f} N | commanded stroke = {row["probe"]["stroke_m"]*1000:.2f} mm',
              'Per-link aggregate positions only; individual contacts, normals and separation were not archived.',
              f'Probe distance from contact target = {probe_distances[index]:.4f} m | Recorded states; no new physics or scores.']
            for line,message in enumerate(lines):draw.text((16,header+height+42+line*27),message,font=small,fill=(220,225,235))
            if a.overlay_dir:
                overlay_index=video_indices.index(index) if a.preview else frame
                overlay_path=a.overlay_dir/name/f'{overlay_index:05}.png'
                with Image.open(overlay_path) as signal_image:
                    canvas.paste(signal_image.convert('RGB'),(width*3-signal_image.width-12,header+height+32))
                draw.text((16,header+height+158),'Native stop: 22.954 deg | common maximum: 23 deg | unchanged canonical32 mapping',font=small,fill=(220,225,235))
                angles=row.get('shaft_limits',{}).get('maximum_angle_rad')
                if angles:
                    draw.text((16,header+height+187),f'Actual shaft tilt: left {math.degrees(angles[0]):.4f} deg | right {math.degrees(angles[1]):.4f} deg',font=small,fill=(220,225,235))
            if a.preview:canvas.save(a.output/f'{name}_preview_{frame}.png')
            else:encoder.stdin.write(canvas.tobytes())
        if encoder:
            encoder.stdin.close()
            if encoder.wait()!=0:raise RuntimeError('video encoder failed')
        item={'case':name,'video':filename if not a.preview else None,'physics_passed':result['physics_passed'],
          'baseline_passed':result['baseline_passed'],'hold_min':result['target_min'],'threshold':result['target_threshold'],
          'termination':result['termination']['reason'],'source_trace':str(trace.relative_to(a.archive)),
          'source_samples':len(rows),'simulation_duration_s':duration,'frames':len(indices),
          'video_duration_s':len(indices)/a.fps if not a.preview else None,'cameras':descriptions,
          'max_probe_replay_position_error_m':probe_error,'point_overlay_counts':counts,'render_wall_s':time.monotonic()-started}
        item.update(framing_policy='fixed controller/contact region; escaped probe labeled' if escaped else 'full archived trajectory',
          framing_neighborhood_m=.06 if escaped else None,max_probe_distance_from_target_m=float(probe_distances.max()),
          probe_outside_panel_frames=probe_outside)
        manifest['cases'].append(item);manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        print('REPLAY_DONE',name,len(indices),round(item['render_wall_s'],2),flush=True)

main();app.close(skip_cleanup=True)
