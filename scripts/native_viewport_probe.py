"""Small native Cycles viewport pilot; left-stick mouse control only.

blender approved.blend --python this.py -- profile.json output_directory
Does not save or change the approved .blend. Esc stops the mouse operator.
"""
import json
import argparse
import math
from pathlib import Path
import re
import sys
import time

import bpy
import gpu
from bpy_extras import view3d_utils as view
from mathutils import Matrix, Vector

parser=argparse.ArgumentParser()
parser.add_argument('profile',type=Path)
parser.add_argument('output',type=Path)
parser.add_argument('--drag-pixel-size',choices=('1','2','4'),default='1')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
profile_path,output=args.profile,args.output
output.mkdir(parents=True, exist_ok=True)
profile = json.loads(profile_path.read_text())
scene = bpy.context.scene
assert scene.get('approved_reference_sha256') == '260187ba839674ce2ed49d5d37c3eeb5ca95206fccb7c13ce2655d7001204907'
events = []
parts = {}
region = space = area = None
left = None


def save_events():
    (output/'events.json').write_text(json.dumps(events, indent=2))


def feasible(q):
    radius = max(1, math.hypot(*q))
    return [v/radius for v in q]


def matrix_for(q):
    q = feasible(q)
    joints = [j for j in profile['joints'] if j['node'] == left.name and j['type'] == 'revolute']
    pivot = Vector(joints[0]['pivot_source_m']) / profile['visual']['meters_per_native_unit']
    matrix = Matrix.Translation(pivot)
    for value, joint in zip(q, joints):
        low, high = joint['limits']
        angle = low + (value+1)*.5*(high-low)
        matrix @= Matrix.Rotation(angle, 4, Vector(joint['axis_source']))
    return matrix @ Matrix.Translation(-pivot)


def project(local, q):
    return view.location_3d_to_region_2d(region, space.region_3d, matrix_for(q) @ local)


def solve(local, initial, target):
    # Same feasible-domain Newton/backtracking method as viewer/drag2d.mjs.
    q = feasible(initial)
    p = project(local, q)
    error = (p-target).length
    clamp = lambda x:max(-1,min(1,x))
    for _ in range(20):
        if error <= .1:
            break
        columns = []
        for i in range(2):
            a,b = q.copy(),q.copy()
            a[i],b[i] = clamp(q[i]+1e-4),clamp(q[i]-1e-4)
            columns.append((project(local,a)-project(local,b))/(a[i]-b[i]))
        (a,c),(b,d) = columns
        det = a*d-b*c
        if abs(det)<1e-8:
            break
        ex,ey = target-p
        step = [(d*ex-b*ey)/det,(-c*ex+a*ey)/det]
        accepted = False
        for k in range(8):
            candidate = feasible([clamp(v+s/(2**k)) for v,s in zip(q,step)])
            next_p = project(local,candidate)
            next_error = (next_p-target).length
            if next_error < error:
                q,p,error = candidate,next_p,next_error
                accepted = True
                break
        if not accepted:
            break
    return q


class XGP_OT_native_stick_probe(bpy.types.Operator):
    bl_idname = 'xgp.native_stick_probe'
    bl_label = 'Xbox native stick pilot'
    dragging = False
    q = [0,0]

    def modal(self, context, event):
        if event.type == 'ESC':
            save_events()
            return {'CANCELLED'}
        xy = Vector((event.mouse_x-region.x,event.mouse_y-region.y))
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            origin = view.region_2d_to_origin_3d(region,space.region_3d,xy)
            direction = view.region_2d_to_vector_3d(region,space.region_3d,xy)
            hit,point,normal,index,obj,matrix = scene.ray_cast(context.evaluated_depsgraph_get(),origin,direction)
            if hit and obj.name == left.name:
                scene.render.preview_pixel_size=args.drag_pixel_size
                self.local = left.matrix_world.inverted() @ point
                self.dragging = True
                events.append({'kind':'press','t':time.monotonic(),'xy':list(xy)})
                return {'RUNNING_MODAL'}
        if self.dragging and event.type == 'MOUSEMOVE':
            before = time.monotonic()
            self.q = solve(self.local,self.q,xy)
            left.matrix_world = matrix_for(self.q)
            events.append({'kind':'pose','t':time.monotonic(),'event_t':before,'q':self.q.copy(),'xy':list(xy)})
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        if self.dragging and event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.dragging = False
            self.q = [0,0]
            scene.render.preview_pixel_size='1'
            left.matrix_world = Matrix.Identity(4)
            events.append({'kind':'release','t':time.monotonic()})
            save_events()
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


def setup():
    global region,space,area,left
    scene.frame_set(0)
    # The accepted recipe hides analytic lights for final renders. Native
    # viewport visibility is separate, so mirror that existing visibility.
    for obj in scene.objects:
        if obj.type == 'LIGHT' and obj.hide_render:
            obj.hide_set(True)
    graph = bpy.context.evaluated_depsgraph_get()
    originals = list(scene.objects)
    helpers = {p.custom_shape for o in originals if o.type=='ARMATURE' for p in o.pose.bones if p.custom_shape}
    meshes = sorted((o for o in originals if o.type=='MESH' and o not in helpers),key=lambda o:o.name)
    assert len(meshes)==16
    for index,obj in enumerate(meshes):
        evaluated = obj.evaluated_get(graph)
        mesh = bpy.data.meshes.new_from_object(evaluated,preserve_all_data_layers=True,depsgraph=graph)
        mesh.transform(evaluated.matrix_world)
        if evaluated.matrix_world.to_3x3().determinant()<0:
            mesh.flip_normals()
        name=obj.name.split('_XBox Gamepad')[0]
        name=f'{index:02d}_{re.sub(r"[^a-zA-Z0-9_-]","_",name)}_VISUAL_UNCALIBRATED'
        part=bpy.data.objects.new(name,mesh);scene.collection.objects.link(part);parts[name]=part
    for obj in originals:
        if obj.type in ('MESH','ARMATURE'):
            bpy.data.objects.remove(obj,do_unlink=True)
    left=parts['09_Stick_L_VISUAL_UNCALIBRATED']
    prefs=bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type='CUDA';prefs.get_devices()
    chosen=next(d for d in prefs.devices if d.type=='CUDA')
    for device in prefs.devices:
        device.use=device==chosen
    scene.cycles.device='GPU'
    scene.cycles.preview_samples=64
    scene.cycles.use_preview_denoising=True
    scene.cycles.preview_denoiser='AUTO'
    scene.render.preview_pixel_size='1'
    window=bpy.context.window
    area=max((a for a in window.screen.areas if a.type=='VIEW_3D'),key=lambda a:a.width*a.height)
    with bpy.context.temp_override(window=window,area=area):
        bpy.ops.screen.screen_full_area(use_hide_panels=True)
    area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
    space=area.spaces.active
    region=next(r for r in area.regions if r.type=='WINDOW')
    space.overlay.show_overlays=False
    space.show_gizmo=False
    space.region_3d.view_perspective='CAMERA'
    space.region_3d.view_camera_zoom=0
    space.shading.type='RENDERED'
    space.shading.use_scene_world_render=True
    space.shading.use_scene_lights_render=True
    bpy.utils.register_class(XGP_OT_native_stick_probe)
    with bpy.context.temp_override(window=window,area=area,region=region):
        bpy.ops.view3d.zoom_camera_1_to_1()
        bpy.ops.xgp.native_stick_probe('INVOKE_DEFAULT')
    bpy.app.timers.register(write_ready,first_interval=10)
    return None


def write_ready():
    points=[left.matrix_world @ Vector(v) for v in left.bound_box]
    point=Vector(((min(v.x for v in points)+max(v.x for v in points))/2,
                  (min(v.y for v in points)+max(v.y for v in points))/2,
                  max(v.z for v in points)))
    origin=project(point,[0,0]);end=project(point,[.6,.8])
    positions={str(r):list(project(point,[.6*r,.8*r])) for r in (0,.2,.4,.6,.8,.9,1)}
    for r in (2,3):
        positions[str(r)]=list(origin+r*(end-origin))
    record={'renderer':gpu.platform.renderer_get(),'vendor':gpu.platform.vendor_get(),
            'cycles_gpu':scene.cycles.device,'preview_samples':scene.cycles.preview_samples,
            'drag_pixel_size':args.drag_pixel_size,'rest_pixel_size':'1',
            'preview_denoising':scene.cycles.use_preview_denoising,'region':[region.x,region.y,region.width,region.height],
            'positions':positions,'ready_t':time.monotonic()}
    (output/'ready.json').write_text(json.dumps(record,indent=2))
    save_events()
    return None


bpy.app.timers.register(setup,first_interval=2)
