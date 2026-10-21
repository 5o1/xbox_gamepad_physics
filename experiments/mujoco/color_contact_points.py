"""Overlay every contact in each displayed archive sample on review videos.

Camera projection uses the recorded fixed cameras. Points are drawn on top,
including occluded points; no physics, contact detection or GPU work is run.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess


def dot(a, b):
    return sum(x*y for x,y in zip(a,b))


def unit(v):
    length = math.sqrt(dot(v,v))
    return [x/length for x in v]


def cross(a, b):
    x,y,z=a;u,v,w=b
    return [y*w-z*v,z*u-x*w,x*v-y*u]


def project(point, camera, width, height):
    forward=unit([a-b for a,b in zip(camera['target_m'],camera['position_m'])])
    right=unit(cross(forward,camera['up']))
    up=cross(right,forward)
    relative=[a-b for a,b in zip(point,camera['position_m'])]
    depth=dot(relative,forward)
    if depth<=0:
        return None
    focal=height/(2*math.tan(math.radians(camera['fovy_deg']/2)))
    return width/2+dot(relative,right)*focal/depth,height/2-dot(relative,up)*focal/depth


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',action='append',dest='cases')
    args=p.parse_args()
    from PIL import Image, ImageDraw, ImageFont
    args.output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((args.source/'video_manifest.json').read_text())
    mapping=json.loads((args.archive/'resources/mujoco/full_controls/mapping_report.json').read_text())
    geom_link={r['geom']:r['link'] for r in mapping['collision']}
    font=ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',20)
    frame_width,frame_height=manifest['frame_resolution'];width,height=manifest['panel_resolution'];header=92
    frame_bytes=frame_width*frame_height*3
    selected=[r for r in manifest['cases'] if args.cases is None or r['case'] in args.cases]
    if args.cases and set(args.cases)-{r['case'] for r in selected}:
        raise ValueError('Unknown video case')

    def annotate(item):
        name=item['case'];trace=args.archive/'evidence/K4'/name/'trace.jsonl'
        assert hashlib.sha256(trace.read_bytes()).hexdigest()==item['source_trace_sha256']
        rows=[json.loads(line) for line in trace.open()]
        src=args.source/item['video'];dst=args.output/item['video']
        decoder=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-threads','2','-i',str(src),
            '-f','rawvideo','-pix_fmt','rgb24','-threads','2','-'],stdout=subprocess.PIPE)
        encoder=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo',
            '-pixel_format','rgb24','-video_size',f'{frame_width}x{frame_height}','-framerate',str(manifest['fps']),
            '-i','-','-an','-c:v','libx264','-threads','3','-preset','fast','-crf','18',
            '-pix_fmt','yuv420p','-movflags','+faststart',str(dst)],stdin=subprocess.PIPE)
        counts={'shell_contacts_in_selected_frames':0,'part_contacts_in_selected_frames':0,
                'nonzero_normal_force_contacts_in_selected_frames':0,'projected_per_panel':[0,0,0],
                'outside_panel_per_panel':[0,0,0],'max_contacts_in_one_frame':0}
        for frame in range(item['frames']):
            raw=decoder.stdout.read(frame_bytes)
            if len(raw)!=frame_bytes:
                raise RuntimeError(f'{name}: missing decoded frame {frame}')
            image=Image.frombytes('RGB',(frame_width,frame_height),raw)
            draw=ImageDraw.Draw(image)
            index=min(len(rows)-1,round(frame*manifest['playback_speed']/(manifest['fps']*.004)))
            contacts=rows[index]['contacts']
            points=[]
            for c in contacts:
                other=next(g for g in c['geoms'] if g!='ruling20_probe')
                shell=geom_link[other]=='controller_body'
                loaded=c['wrench_contact_n_nm'][0]>1e-9
                points.append((c['point_m'],shell,loaded))
            shell_count=sum(shell for _,shell,_ in points);part_count=len(points)-shell_count
            counts['shell_contacts_in_selected_frames']+=shell_count
            counts['part_contacts_in_selected_frames']+=part_count
            counts['nonzero_normal_force_contacts_in_selected_frames']+=sum(loaded for _,_,loaded in points)
            counts['max_contacts_in_one_frame']=max(counts['max_contacts_in_one_frame'],len(points))
            # Loaded points remain visible when projections overlap zero-force points.
            points.sort(key=lambda point:point[2])
            for panel,camera in enumerate(item['cameras']):
                layer=Image.new('RGBA',(width,height),(0,0,0,0));painter=ImageDraw.Draw(layer)
                for position,shell,loaded in points:
                    xy=project(position,camera,width,height)
                    if xy is None or not (0<=xy[0]<width and 0<=xy[1]<height):
                        counts['outside_panel_per_panel'][panel]+=1
                        continue
                    counts['projected_per_panel'][panel]+=1
                    x,y=xy;color=(255,40,70,255) if shell else (40,255,110,255)
                    painter.ellipse((x-5,y-5,x+5,y+5),fill=(255,255,255,255))
                    painter.ellipse((x-4,y-4,x+4,y+4),fill=color)
                    if not loaded:
                        painter.ellipse((x-2,y-2,x+2,y+2),fill=(35,42,52,255))
                image.paste(layer,(panel*width,header),layer)
            draw=ImageDraw.Draw(image)
            draw.rectangle((0,665,frame_width,694),fill=(20,25,34))
            draw.text((16,665),f'外壳触点：{shell_count}',font=font,fill=(255,60,90),anchor='lt')
            draw.text((235,665),f'活动件触点：{part_count}',font=font,fill=(40,255,110),anchor='lt')
            draw.text((475,665),'实心＝有法向力；空心＝零法向力记录。所有点覆盖显示，遮挡点也可见。',font=font,fill=(235,240,245),anchor='lt')
            encoder.stdin.write(image.tobytes())
        decoder.stdout.close();encoder.stdin.close()
        if decoder.wait()!=0 or encoder.wait()!=0:
            raise RuntimeError(f'{name}: video processing failed')
        print(name,counts,flush=True)
        return {**item,'point_overlay_counts':counts}

    with ThreadPoolExecutor(max_workers=2) as workers:
        items=list(workers.map(annotate,selected))
    manifest['cases']=items
    manifest['contact_marker']='Every contact in the selected archived sample is projected and overlaid in all three panels, including occluded points. Red/white=controller-body shell, green/white=moving part; filled=normal force >1e-9 N, hollow=zero normal force.'
    manifest['point_overlay']={'method':'CPU projection onto existing frames; no GPU or physics.',
        'shell_color':'#ff2846','part_color':'#28ff6e','always_on_top':True,'source_frequency_hz':250,
        'video_frame_sample_rule':'Same nearest-sample selection as original replay.',
        'note':'Coincident projected markers may overlap. These are recorded outer-step contacts, not unrecorded inner-substep contacts.'}
    (args.output/'video_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
