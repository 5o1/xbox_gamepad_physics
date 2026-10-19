"""Render archived acceptance trajectories as synchronized three-view videos.

Replay sets recorded coordinates and runs kinematics only. It never steps the
physics or re-scores the experiment. Contact markers come from the archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time


def rotation(mj, np, quat):
    matrix = np.empty(9)
    mj.mju_quat2Mat(matrix, np.asarray(quat, dtype=float))
    return matrix.reshape(3, 3)


def point_camera(mj, np, camera, position, target, up):
    forward = np.asarray(target) - position
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    vertical = np.cross(right, forward)
    quat = np.empty(4)
    mj.mju_mat2Quat(quat, np.column_stack([right, vertical, -forward]).reshape(-1))
    camera.pos[:] = position
    camera.quat[:] = quat


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--case', action='append', dest='cases')
    p.add_argument('--fps', type=int, default=30)
    p.add_argument('--speed', type=float, default=.5)
    p.add_argument('--preview', action='store_true', help='Render three diagnostic stills per case only.')
    args = p.parse_args()
    os.environ['MUJOCO_GL'] = 'egl'
    os.environ['MUJOCO_EGL_DEVICE_ID'] = '3'
    import mujoco as mj
    import numpy as np
    from OpenGL import GL
    from PIL import Image, ImageDraw, ImageFont
    from mujoco.rendering.classic import renderer as classic
    from xbox_gamepad_physics.acceptance import load_suite
    from xbox_gamepad_physics.acceptance.scoring import target_value
    from xbox_gamepad_physics.mujoco import make_spec
    from xbox_gamepad_physics.mujoco.numerics import apply_standalone_policy

    args.output.mkdir(parents=True, exist_ok=True)
    suite = load_suite()
    results = json.loads((args.archive / 'evidence/K4/results.json').read_text())
    summaries = {r['case']: r for r in results['results']}
    wanted = args.cases or [c.case_id for c in suite.cases]
    asset = make_spec(resource_root=args.archive / 'resources', fixed_root=True, attach_visual=True)
    spec = asset.spec
    apply_standalone_policy(spec.option, asset.numerical_policy)
    for name in ('front', 'top', 'side'):
        spec.worldbody.add_camera(name='replay_' + name, fovy=32)
    body = spec.worldbody.add_body(name='replay_probe', pos=[0, 0, 1])
    body.mass = suite.settings['mass_kg']
    body.ipos = [0, 0, 0]
    body.iquat = [1, 0, 0, 0]
    body.inertia = [2*suite.settings['mass_kg']*suite.settings['radius_m']**2/5]*3
    body.explicitinertial = True
    body.add_freejoint(name='replay_probe_free')
    body.add_geom(name='replay_probe', type=mj.mjtGeom.mjGEOM_SPHERE,
                  size=[suite.settings['radius_m'], 0, 0], mass=suite.settings['mass_kg'],
                  rgba=[.95, .15, .08, 1], group=0)
    # Lighting and camera changes are presentation only.
    spec.worldbody.add_light(name='replay_key', pos=[0, -.1, .6], dir=[0, 0, -1],
                            diffuse=[.6, .6, .6], castshadow=False)
    spec.add_texture(name='replay_background', type=mj.mjtTexture.mjTEXTURE_SKYBOX,
                     builtin=mj.mjtBuiltin.mjBUILTIN_FLAT, rgb1=[.16,.19,.23],
                     rgb2=[.16,.19,.23], width=16, height=96)
    model = spec.compile()
    data = mj.MjData(model)
    handle = asset.bind(model, data)
    joint_addresses = {n: int(model.joint(n).qposadr[0]) for n in handle.joint_names}
    velocity_addresses = {n: int(model.joint(n).dofadr[0]) for n in handle.joint_names}
    probe_address = int(model.joint('replay_probe_free').qposadr[0])
    root_id = int(model.body('controller_body').id)
    width, height, header, footer = 640, 480, 92, 174
    model.vis.global_.offwidth = width
    model.vis.global_.offheight = height
    model.vis.quality.offsamples = 1
    model.vis.quality.shadowsize = 128
    model.stat.extent = .2
    model.vis.map.znear, model.vis.map.zfar = .0005, 20
    model.vis.headlight.ambient[:] = .4
    model.vis.headlight.diffuse[:] = .7
    model.vis.headlight.specular[:] = .15
    original_rgba = model.geom_rgba.copy()
    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font = ImageFont.truetype(font_path, 22)
    small = ImageFont.truetype(font_path, 18)
    large = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 32)
    record = {'schema': 'mujoco-archived-contact-video-v1', 'mujoco': mj.__version__,
              'source_archive': str(args.archive), 'collision': results['collision'],
              'mode': 'Recorded qpos/probe pose and archived contacts; kinematics only; no physics steps.',
              'fps': args.fps, 'playback_speed': args.speed, 'egl_device_id': 3,
              'panel_resolution': [width, height], 'frame_resolution': [3*width, height+header+footer],
              'contact_marker': 'Green dots: archived contact points; positions are not recomputed.',
              'side_panel': 'Translucent source collision shells; reference triangles, not a reconstructed SDF isosurface. Orange shells were contacted in this case.',
              'cases': []}
    manifest_path = args.output / ('preview_manifest.json' if args.preview else 'video_manifest.json')

    for name in wanted:
        case = suite.case(name)
        trace = args.archive / 'evidence/K4' / name / 'trace.jsonl'
        rows = [json.loads(line) for line in trace.open()]
        result = summaries[name]
        root_position = np.asarray(rows[0]['root_pose']['position_m'])
        root_quat = rows[0]['root_pose']['orientation_wxyz']
        root_rotation = rotation(mj, np, root_quat)
        model.body_pos[root_id] = root_position
        model.body_quat[root_id] = root_quat
        data.qpos[:] = model.qpos0
        data.qvel[:] = 0
        for joint, value in asset.manifest['initial_positions'].items():
            data.qpos[joint_addresses[joint]] = value
        mj.mj_kinematics(model, data)
        mj.mj_comPos(model, data)
        # Determine fixed front framing from all original visual vertices.
        points = []
        for g in range(model.ngeom):
            if int(model.geom_group[g]) != 1:
                continue
            mesh = int(model.geom_dataid[g])
            start, count = int(model.mesh_vertadr[mesh]), int(model.mesh_vertnum[mesh])
            world = model.mesh_vert[start:start+count] @ data.geom_xmat[g].reshape(3, 3).T + data.geom_xpos[g]
            points.append((world-root_position) @ root_rotation)
        visual = np.concatenate(points)
        balls = (np.asarray([r['probe']['pose'][:3] for r in rows])-root_position) @ root_rotation
        planned = (np.asarray(case.plan['point_m'])-root_position) @ root_rotation
        whole = np.concatenate([visual, balls])
        front_target = (whole.min(axis=0)+whole.max(axis=0))/2
        close = np.concatenate([balls, planned[None, :]])
        close_target = (close.min(axis=0)+close.max(axis=0))/2
        aspect = width/height
        margin = .012
        # Orthogonal camera directions in the controller's local frame.
        side_sign = -1 if planned[0] < 0 else 1
        definitions = [
            ('front', front_target, np.array([0., 0., 1.]), np.array([0., 1., 0.]), whole, .014),
            ('top', close_target, np.array([0., 1., 0.]), np.array([0., 0., 1.]), close, margin),
            ('side', close_target, np.array([float(side_sign), 0., 0.]), np.array([0., 0., 1.]), close, margin)]
        cameras = []
        for camera_name, center, direction, up, bounds, padding in definitions:
            right = np.cross(-direction, up)
            vertical = np.cross(right, -direction)
            spans = np.ptp(bounds @ np.column_stack([right, vertical]), axis=0)
            visible_height = max(spans[1]+2*padding, (spans[0]+2*padding)/aspect, .045)
            distance = visible_height/(2*math.tan(math.radians(16))) + .035
            target = root_position + root_rotation @ center
            pos = target + root_rotation @ direction * distance
            cam_id = int(model.camera('replay_'+camera_name).id)
            point_camera(mj, np, model.camera(cam_id), pos, target, root_rotation @ up)
            cameras.append({'name': camera_name, 'position_m': pos.tolist(), 'target_m': target.tolist(),
                            'up': (root_rotation @ up).tolist(), 'fovy_deg': 32,
                            'controller_local_direction': direction.tolist()})
        contact_names = {g for row in rows for c in row['contacts'] for g in c['geoms'] if g != 'ruling20_probe'}
        collision_ids = [g for g in range(model.ngeom) if int(model.geom_group[g]) == 3]
        duration = len(rows)*.004
        count = math.ceil(duration/args.speed*args.fps)+1
        if args.preview:
            hold = [i for i,r in enumerate(rows) if r['probe']['phase']=='hold']
            least = min(hold, key=lambda i: target_value(case.plan, rows[i]['signals'], rows[i]['probe']['events']))
            frame_indices = [0, least, len(rows)-1]
        else:
            frame_indices = [min(len(rows)-1, round(frame*args.speed/(args.fps*.004))) for frame in range(count)]
        file = args.output / f'{name}_three_views.mp4'
        process = None
        if not args.preview:
            process = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'{3*width}x{height+header+footer}',
                '-framerate', str(args.fps), '-i', '-', '-an', '-c:v', 'libx264', '-threads', '4',
                '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(file)], stdin=subprocess.PIPE)
        started = time.perf_counter()
        replay_error = 0.
        with classic.Renderer(model, height=height, width=width) as renderer:
            vendor = GL.glGetString(GL.GL_VENDOR).decode()
            gpu = GL.glGetString(GL.GL_RENDERER).decode()
            if 'nvidia' not in vendor.lower():
                raise RuntimeError(f'GPU EGL required; got {vendor}: {gpu}')
            for output_frame, index in enumerate(frame_indices):
                row = rows[index]
                assert row['root_pose'] == rows[0]['root_pose']
                for joint, value in row['joints'].items():
                    data.qpos[joint_addresses[joint]] = value
                    data.qvel[velocity_addresses[joint]] = row['joint_velocities'][joint]
                data.qpos[probe_address:probe_address+7] = row['probe']['pose']
                data.time = (row['step']+1)*.004
                mj.mj_kinematics(model, data)
                mj.mj_comPos(model, data)
                mj.mj_camlight(model, data)
                replay_error = max(replay_error, float(np.max(abs(data.xpos[model.body('replay_probe').id]-row['probe']['pose'][:3]))))
                canvas = Image.new('RGB', (3*width, height+header+footer), (20, 25, 34))
                draw = ImageDraw.Draw(canvas)
                color = (51, 255, 119) if result['physics_passed'] else (255, 48, 48)
                draw.text((18, 4), f'{name} | SDF 接触实验 | {"成功" if result["physics_passed"] else "失败"} | {args.speed:g}倍速', font=large, fill=color, anchor='lt')
                signal = target_value(case.plan, row['signals'], row['probe']['events'])
                phase = row['probe']['phase'].upper()
                draw.text((18, 45), f't = {data.time:.3f} s   {phase:<10} target signal = {signal:+.4f}   hold minimum = {result["target_min"]:+.4f} / required {result["target_threshold"]:.2f}', font=font, fill='white')
                for panel, camera_name in enumerate(('front', 'top', 'side')):
                    model.geom_rgba[:] = original_rgba
                    option = mj.MjvOption()
                    option.geomgroup[3] = 0
                    if panel == 2:
                        option.geomgroup[1] = 0
                        option.geomgroup[3] = 1
                        for g in collision_ids:
                            model.geom_rgba[g] = [.95,.58,.12,.35] if model.geom(g).name in contact_names else [.3,.65,.95,.18]
                    renderer.update_scene(data, camera='replay_'+camera_name, scene_option=option)
                    renderer.scene.flags[mj.mjtRndFlag.mjRND_SHADOW] = False
                    for contact in row['contacts']:
                        if renderer.scene.ngeom >= renderer.scene.maxgeom:
                            break
                        geom = renderer.scene.geoms[renderer.scene.ngeom]
                        mj.mjv_initGeom(geom, mj.mjtGeom.mjGEOM_SPHERE, np.array([.00035,0,0]),
                            np.asarray(contact['point_m']), np.eye(3).reshape(-1), np.array([.15,1.,.35,1.]))
                        renderer.scene.ngeom += 1
                    pixels = renderer.render().copy()
                    canvas.paste(Image.fromarray(pixels), (panel*width, header))
                    labels = ['FRONT | full controller, straight on', 'TOP | fixed contact close-up', 'SIDE | translucent collision shells']
                    draw.text((panel*width+12, header+height+8), labels[panel], font=small, fill=(200,225,250))
                for divider in (width, 2*width):
                    draw.line((divider, header, divider, header+height), fill=(110,125,145), width=2)
                contacts = row['contacts']
                targets = sorted({g for c in contacts for g in c['geoms'] if g != 'ruling20_probe'})
                depth = max([max(0., -c['separation_m'])*1000 for c in contacts] or [0.])
                stop = row['probe']['termination']['reason'] if row['probe']['termination'] else 'press not stopped yet'
                text = [f'Contact: {", ".join(targets) if targets else "none"}   | max recorded penetration = {depth:.3f} mm',
                        f'Stop: {stop}   | force = {np.linalg.norm(row["probe"]["force_n"]):.2f} N   | commanded stroke = {row["probe"]["stroke_m"]*1000:.2f} mm',
                        'Red: actual probe. Green: archived contact points. Orange side shells: contacted during this case.',
                        'Recorded trajectory replay at 250 Hz; frames select nearest sample. No new physics or parameter changes.']
                for line, message in enumerate(text):
                    draw.text((16, header+height+42+line*27), message, font=small, fill=(220,225,235))
                if args.preview:
                    canvas.save(args.output/f'{name}_preview_{output_frame}.png')
                else:
                    process.stdin.write(canvas.tobytes())
        model.geom_rgba[:] = original_rgba
        if process is not None:
            process.stdin.close()
            if process.wait() != 0:
                raise RuntimeError('ffmpeg encoding failed')
        item = {'case': name, 'source_trace_sha256': hashlib.sha256(trace.read_bytes()).hexdigest(),
                'source_samples': len(rows), 'simulation_duration_s': duration, 'frames': len(frame_indices),
                'video_duration_s': len(frame_indices)/args.fps if not args.preview else None,
                'video': file.name if not args.preview else None, 'physics_passed': result['physics_passed'],
                'baseline_passed': result['baseline_passed'], 'hold_min': result['target_min'],
                'termination': result['termination']['reason'], 'cameras': cameras,
                'max_probe_replay_position_error_m': replay_error,
                'renderer': gpu, 'render_wall_s': time.perf_counter()-started}
        record['cases'].append(item)
        manifest_path.write_text(json.dumps(record, indent=2)+'\n')
        print(name, len(frame_indices), f'{item["render_wall_s"]:.2f}s', flush=True)
        # Release EGL resources between short per-case GPU batches.
        time.sleep(.2)


if __name__ == '__main__':
    main()
