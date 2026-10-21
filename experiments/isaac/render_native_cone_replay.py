"""Render synchronized front, top and right orthographic views of saved q.

Only row zero was archived. Free-root world poses were not recorded, so its
replay is explicitly relative to the controller body. No physics is rerun.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time

from isaaclab.app import AppLauncher

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--archive', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--case', action='append', required=True, dest='cases')
p.add_argument('--preview', action='store_true')
p.add_argument('--fps', type=int, default=30)
p.add_argument('--speed', type=float, default=.1)
AppLauncher.add_app_launcher_args(p)
a = p.parse_args()
launcher = AppLauncher(a, renderer='RaytracedLighting')
app = launcher.app

try:
    import numpy as np
    import carb
    import omni.usd
    import omni.timeline
    import omni.replicator.core as rep
    from pxr import Usd, UsdGeom, UsdLux, Gf, Tf
    from PIL import Image, ImageDraw, ImageFont
    from xbox_gamepad_physics.motion import motion_from_dict
    from xbox_gamepad_physics.backends.common.model import Pose
    from xbox_gamepad_physics.backends.common.transforms import compose, rotate

    a.output.mkdir(parents=True, exist_ok=True)
    motion = motion_from_dict(json.loads((a.archive/'resources/common/xbox_one_s/motion/full_controls.json').read_text()))
    names = None

    def poses_for(q):
        poses = {'controller_body': Pose()}
        pending = list(motion.joints)
        while pending:
            ready = [joint for joint in pending if joint.parent in poses]
            if not ready:
                raise ValueError('disconnected common motion chain')
            for joint in ready:
                frame = compose(poses[joint.parent], Pose(joint.origin, joint.origin_orientation_wxyz))
                value = q[joint.name]
                if joint.kind == 'prismatic':
                    delta = Pose(tuple(value*x for x in joint.axis))
                else:
                    norm = math.sqrt(sum(x*x for x in joint.axis))
                    delta = Pose(orientation_wxyz=(math.cos(value/2),
                        *(math.sin(value/2)*x/norm for x in joint.axis)))
                poses[joint.child] = compose(frame, delta)
                pending.remove(joint)
        return poses

    omni.usd.get_context().new_stage()
    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageMetersPerUnit(stage, 1.)
    UsdGeom.SetStageUpAxis(stage, 'Z')
    timeline = omni.timeline.get_timeline_interface()
    timeline.stop()
    first = a.archive/'output'/a.cases[0]
    models = []
    operations = []
    offsets = [np.full(3, panel*.5) for panel in range(3)]
    for panel in range(3):
        root = UsdGeom.Xform.Define(stage, f'/World/View{panel}')
        root.GetPrim().GetReferences().AddReference(str(first/'pad.usda'))
        models.append(root)
        links = {}
        for link in ['controller_body']+[j.child for j in motion.joints]:
            prim = stage.GetPrimAtPath(f'/World/View{panel}/Links/'+Tf.MakeValidIdentifier(link))
            xform = UsdGeom.Xformable(prim)
            xform.ClearXformOpOrder()
            links[link] = xform.AddTransformOp(UsdGeom.XformOp.PrecisionDouble, 'replay')
        operations.append(links)

    dome = UsdLux.DomeLight.Define(stage, '/World/ReplayDome')
    dome.CreateColorAttr(Gf.Vec3f(.8, .85, 1.)); dome.CreateIntensityAttr(300.)
    light = UsdLux.DistantLight.Define(stage, '/World/ReplayKey')
    light.CreateIntensityAttr(600.)
    light.AddRotateXYZOp().Set(Gf.Vec3f(-30., -20., 30.))
    width, height, header, footer = 640, 480, 88, 152
    settings = carb.settings.get_settings()
    render_settings = {'/rtx/rendermode': 'RaytracedLighting', '/rtx/post/aa/op': 0,
        '/rtx/translucency/enabled': True, '/rtx/raytracing/fractionalCutoutOpacity': True,
        '/rtx/reflections/enabled': True, '/rtx/indirectDiffuse/enabled': True,
        '/rtx/multiGpu/enabled': False, '/rtx/material/translucencyAsOpacity': False,
        '/rtx/sceneDb/translucencyAsOpacity': False}
    for key, value in render_settings.items():
        settings.set(key, value)
    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font = ImageFont.truetype(font_path, 23)
    small = ImageFont.truetype(font_path, 18)
    title_font = ImageFont.truetype(font_path, 27)
    cameras = []
    camera_prims = []
    annotations = []
    for panel in range(3):
        camera = UsdGeom.Camera.Define(stage, f'/World/Camera{panel}')
        camera.CreateProjectionAttr(UsdGeom.Tokens.orthographic)
        camera.CreateClippingRangeAttr(Gf.Vec2f(.0005, 20.))
        camera_prims.append(camera)
        cameras.append(camera.AddTransformOp())
        product = rep.create.render_product(str(camera.GetPath()), (width, height))
        annotator = rep.AnnotatorRegistry.get_annotator('HdrColor', device='cpu')
        annotator.attach([product]); annotations.append(annotator)

    manifest = {'mode': 'Archived row-zero joint coordinates; body-relative USD replay',
        'source_usd': str((first/'pad.usda').relative_to(a.archive)),
        'replay_transform': 'double-precision matrix; source USD files remain unchanged',
        'physics_steps': 0, 'state_projection': False, 'interpolation': False,
        'fps': a.fps, 'playback_speed': a.speed,
        'resolution': [3*width, height+header+footer], 'render_settings': render_settings,
        'camera_layout': 'front_top_right_orthographic', 'same_object_and_sample': True,
        'free_root_world_motion': 'not recorded and not reconstructed', 'cases': []}

    def set_poses(poses):
        for panel in range(3):
            for link, pose in poses.items():
                transform = Gf.Matrix4d(1.)
                transform.SetRotate(Gf.Quatd(pose.orientation_wxyz[0], Gf.Vec3d(*pose.orientation_wxyz[1:])))
                transform.SetTranslateOnly(Gf.Vec3d(*(np.asarray(pose.position_m)+offsets[panel])))
                operations[panel][link].Set(transform)

    for case in a.cases:
        folder = a.archive/'output'/case
        record = json.loads((folder/'result.json').read_text())
        strict_passed = all(check['passed'] for check in record['strict_contract'].values())
        rows = json.loads((folder/'trajectory.json').read_text())
        names = record['native_readback']['joint_names']
        if len(names) != 20 or any(len(row) != 43 for row in rows):
            raise ValueError('expected archived row-zero [tick, angles2, q20, v20]')
        all_poses = [poses_for(dict(zip(names, row[3:23]))) for row in rows]
        angles = np.rad2deg(np.asarray(rows)[:, 1:3])
        maximum = angles.max(0)
        peak = int(np.argmax(angles.max(1)))
        set_poses(all_poses[0])
        box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default']).ComputeWorldBound(models[0].GetPrim()).ComputeAlignedRange()
        low, high = np.asarray(box.GetMin()), np.asarray(box.GetMax())
        center = (low+high)/2
        corners = np.asarray([[x, y, z] for x in (low[0], high[0])
            for y in (low[1], high[1]) for z in (low[2], high[2])])
        definitions = [('FRONT', np.array([0., 0., 1.]), np.array([0., 1., 0.])),
                       ('TOP', np.array([0., 1., 0.]), np.array([0., 0., 1.])),
                       ('RIGHT', np.array([1., 0., 0.]), np.array([0., 0., 1.]))]
        visible_height = 0.
        for _, direction, up in definitions:
            right = np.cross(-direction, up)
            projected = corners @ np.column_stack((right, up))
            span = np.ptp(projected, axis=0)
            visible_height = max(visible_height, span[1]+.02, (span[0]+.02)/(width/height))
        camera_records = []
        for panel, (label, direction, up) in enumerate(definitions):
            # USD camera apertures are measured in tenths of scene units.
            camera_prims[panel].CreateVerticalApertureAttr(visible_height*10.)
            camera_prims[panel].CreateHorizontalApertureAttr(visible_height*10.*width/height)
            position = center+direction*(np.max(high-low)+.1)
            cameras[panel].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*(position+offsets[panel])),
                Gf.Vec3d(*(center+offsets[panel])), Gf.Vec3d(*up)).GetInverse())
            native_axis = camera_prims[panel].ComputeLocalToWorldTransform(Usd.TimeCode.Default()).TransformDir(Gf.Vec3d(0., 0., 1.))
            assert np.allclose(native_axis, direction, atol=1e-12, rtol=0.)
            assert camera_prims[panel].GetProjectionAttr().Get() == 'orthographic'
            camera_records.append({'name': label, 'projection': 'orthographic',
                'position_m': position.tolist(), 'target_m': center.tolist(),
                'eye_axis_body': direction.tolist(), 'up_body': up.tolist(),
                'vertical_span_m': visible_height, 'axis_readback_verified': True})
        for _ in range(16):
            app.update()
        indices = [0, peak, len(rows)-1] if a.preview else [
            min(len(rows)-1, round(frame*a.speed/(a.fps*.004)))
            for frame in range(math.ceil(len(rows)*.004/a.speed*a.fps))]
        filename = case+'.mp4'
        encoder = None
        if not a.preview:
            encoder = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-video_size', f'{3*width}x{height+header+footer}',
                '-framerate', str(a.fps), '-i', '-', '-an', '-c:v', 'libx264', '-threads', '3',
                '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                str(a.output/filename)], stdin=subprocess.PIPE)
        started = time.monotonic()
        last_index = None
        canvas = None
        geometry_error = 0.
        usd_angle_error = 0.
        for frame, index in enumerate(indices):
            if index != last_index:
                poses = all_poses[index]
                set_poses(poses)
                app.update(); app.update()
                assert not timeline.is_playing(), 'video replay must not advance physics'
                canvas = Image.new('RGB', (3*width, height+header+footer), (20, 25, 34))
                draw = ImageDraw.Draw(canvas)
                kind = 'BOUNDARY START' if record.get('boundary_start') else 'NEUTRAL START'
                status = 'PASS' if strict_passed else 'FAIL'
                draw.text((16, 5), f'Native PhysX cone | {kind} | {record["root_mode"]} N={record["num_envs"]} | STRICT LIMIT: {status}',
                    font=title_font, fill=(65, 235, 125) if strict_passed else (255, 75, 75))
                draw.text((16, 45), f't = {(rows[index][0]+1)*.004:.3f} s | row 0 | {a.speed:g}x speed | two hinges + cone | no state projection',
                    font=font, fill='white')
                for panel, annotator in enumerate(annotations):
                    raw = annotator.get_data()
                    assert isinstance(raw, np.ndarray) and raw.shape == (height, width, 4) and np.isfinite(raw).all()
                    linear = np.maximum(raw[..., :3].astype(np.float32), 0.)
                    rgb = np.where(linear <= .0031308, 12.92*linear, 1.055*linear**(1/2.4)-.055)
                    picture = Image.fromarray(np.rint(np.clip(rgb, 0., 1.)*255).astype(np.uint8))
                    canvas.paste(picture, (panel*width, header))
                    label = ['FRONT (+Z)', 'TOP (+Y)', 'RIGHT (+X)'][panel]+' | ORTHOGRAPHIC, SAME SCALE'
                    draw.text((panel*width+12, header+height+6), label, font=small, fill=(200, 225, 250))
                for column, side in enumerate(('left', 'right')):
                    axis = np.asarray(rotate(poses[side+'_stick_y_frame'].orientation_wxyz, (0., 0., 1.)))
                    actual_angle = math.atan2(np.linalg.norm(axis[:2]), axis[2])
                    geometry_error = max(geometry_error, abs(actual_angle-rows[index][1+column]))
                    prim = stage.GetPrimAtPath('/World/View0/Links/'+side+'_stick_y_frame')
                    transform = UsdGeom.XformCache().GetLocalToWorldTransform(prim)
                    native_axis = np.asarray(transform.TransformDir(Gf.Vec3d(0., 0., 1.)))
                    native_angle = math.atan2(np.linalg.norm(native_axis[:2]), native_axis[2])
                    usd_angle_error = max(usd_angle_error, abs(native_angle-rows[index][1+column]))
                    cx, cy, radius = 2*width+170+column*280, header+height+82, 36
                    draw.text((cx-28, header+height+28), side.upper(), font=small, fill=(220, 225, 235))
                    draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), outline=(220, 225, 235), width=2)
                    footprint = axis[:2]/axis[2]/math.tan(math.radians(23.))
                    x, y = cx+radius*footprint[0], cy-radius*footprint[1]
                    color = (255, 75, 75) if angles[index, column] > 23. else (65, 235, 125)
                    draw.ellipse((x-4, y-4, x+4, y+4), fill=color)
                    draw.text((width+12, header+height+38+column*40),
                        f'{side.upper()} tilt {angles[index,column]:.6f} deg | peak {maximum[column]:.6f}', font=small, fill=color)
                draw.text((width+12, header+height+118), 'Actual recorded tilt | limit = 23 deg', font=small, fill=(190, 200, 215))
                draw.text((2*width+12, header+height+124), '23 deg shaft envelopes | same recorded sample', font=small, fill=(190, 200, 215))
                note = ['Recorded q, native Isaac rendering.', 'No new simulation or scoring.', 'No interpolation or angle clamp.']
                if record['root_mode'] == 'free':
                    note = ['BODY-RELATIVE REPLAY.', 'Free-root world pose was not saved.', 'Only row 0 of the batch is shown.']
                for line, message in enumerate(note):
                    draw.text((12, header+height+38+line*28), message, font=small, fill=(255, 215, 105))
                last_index = index
            if a.preview:
                canvas.save(a.output/f'{case}_preview_{frame}.png')
            else:
                encoder.stdin.write(canvas.tobytes())
        if encoder:
            encoder.stdin.close()
            if encoder.wait() != 0:
                raise RuntimeError('video encoding failed')
        manifest['cases'].append({'case': case, 'video': filename if not a.preview else None,
            'source_result': str((folder/'result.json').relative_to(a.archive)),
            'source_trace': str((folder/'trajectory.json').relative_to(a.archive)),
            'root_mode': record['root_mode'], 'num_envs_in_source_run': record['num_envs'], 'rendered_env_id': 0,
            'body_relative': True, 'source_samples': len(rows), 'simulation_duration_s': len(rows)*.004,
            'frames': len(indices), 'selected_sample_indices': indices,
            'peak_sample_index': peak,
            'recorded_row_peak_deg': maximum.tolist(),
            'whole_run_peak_deg': record['strict_contract']['every_substep_inside']['peak_angle_deg'],
            'source_strict_contract_passed': strict_passed, 'source_status': record['status'],
            'maximum_geometry_angle_error_rad': geometry_error,
            'maximum_usd_angle_error_rad': usd_angle_error, 'cameras': camera_records,
            'render_seconds': time.monotonic()-started})
        (a.output/('preview_manifest.json' if a.preview else 'video_manifest.json')).write_text(json.dumps(manifest, indent=2)+'\n')
        print('CONE_REPLAY_DONE', case, len(indices), round(time.monotonic()-started, 2), flush=True)
finally:
    app.close(skip_cleanup=True)
