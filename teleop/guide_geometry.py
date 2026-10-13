"""Read cooked CoACD pocket surfaces at neutral and press-depth positions."""
import argparse,json,math
from pathlib import Path
from .record import iter_records


def run(output, reference_trace):
    import numpy as np
    from scipy.spatial import ConvexHull
    from .runtime import make_session
    from .server import live_config
    from .ball_probe import cooked_vertices,contact_plan,SETTINGS
    from xbox_gamepad_physics.resources import resource_root,resource_path
    output.mkdir(parents=True,exist_ok=True)
    cfg=live_config(Path('configs/teleop_gripper.yaml'), collision='coacd');cfg['teleop']['initial_pose']=[1,1,1,1,0,0,0]
    session=make_session(cfg,output)
    links={l.name:l for l in session.gamepad.articulation.get_links()}
    plan=contact_plan(session.gamepad,'Guide',SETTINGS)
    center=np.asarray(plan['point_m'][:2]);top=plan['point_m'][2]
    shell_vertices=cooked_vertices(links['controller_body'])
    # Use actual SAPIEN cooked vertices, not visual triangles or collision AABBs.
    hulls=[{'planes':ConvexHull(v).equations,'xy_min':v[:,:2].min(0),'xy_max':v[:,:2].max(0)} for v in shell_vertices]
    def height(xy):
        tops=[]
        for i,h in enumerate(hulls):
            if np.any(xy<h['xy_min']-1e-9) or np.any(xy>h['xy_max']+1e-9):continue
            eq=h['planes'];b=eq[:,:2]@xy+eq[:,3];z=eq[:,2]
            flat=np.abs(z)<1e-10
            if np.any(b[flat]>1e-7):continue
            low=max((-b[z< -1e-10]/z[z< -1e-10]).tolist(),default=-float('inf'))
            high=min((-b[z>1e-10]/z[z>1e-10]).tolist(),default=float('inf'))
            if low<=high and math.isfinite(high):tops.append((high,i))
        return max(tops) if tops else (None,None)
    trace=list(iter_records(reference_trace))
    held=[r for r in trace if r['probe']['phase']=='hold'][-125:]
    contact=[]
    for row in held:
        for c in row['contacts']:
            if 'gamepad/controller_body' not in c['bodies']:continue
            for p in c['points']:
                if np.linalg.norm(p['impulse_ns'])<=1e-10:continue
                xy=np.asarray(p['position_m'][:2]);z,i=height(xy)
                if z is not None:contact.append({'xy_m':xy.tolist(),'rim_z_m':z,'hull_index':i,'contact_z_m':p['position_m'][2]})
    rim=np.asarray([c['rim_z_m'] for c in contact])
    sections=[]
    for axis,vector in [('x',[1,0]),('y',[0,1])]:
        for offset in np.linspace(-.006,.006,241):
            xy=center+offset*np.asarray(vector);z,i=height(xy)
            sections.append({'axis':axis,'offset_mm':float(offset*1000),'shell_top_z_mm':None if z is None else z*1000,'hull_index':i})
    manifest=json.loads(resource_path('robotwin','full_controls','collision/manifest.json').read_text())
    result={'method':'upper surface of actual cooked convex hulls at the 4 mm ball load-bearing shell contact XY positions; cut sections included',
            'resource_root':str(resource_root()),'collision':'coacd','sapien':__import__('sapien').__version__,
            'meshes':{n:manifest['links'][n]['coacd'] for n in ['guide','controller_body']},
            'cooked_shape_counts':{n:len(links[n].get_collision_shapes()) for n in ['guide','controller_body']},
            'root_pose':list(map(float,(*session.gamepad.articulation.root.pose.p,*session.gamepad.articulation.root.pose.q))),
            'guide_center_xy_m':center.tolist(),'neutral_guide_top_z_mm':top*1000,
            'load_bearing_rim_z_mm':{'minimum':float(rim.min()*1000),'maximum':float(rim.max()*1000),'mean':float(rim.mean()*1000)},
            'rim_minus_neutral_guide_top_mm':{'minimum':float((rim.min()-top)*1000),'maximum':float((rim.max()-top)*1000)},
            'guide_stroke_mm':plan['limits'][0][1]*1000,
            'rim_minus_95percent_pressed_top_mm':{'minimum':float((rim.min()-top+.95*plan['limits'][0][1])*1000),'maximum':float((rim.max()-top+.95*plan['limits'][0][1])*1000)},
            'source_trace':str(reference_trace),'load_bearing_samples':contact,'sections':sections}
    (output/'geometry.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('sections','load_bearing_samples')}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--reference-trace',type=Path,required=True)
    a=p.parse_args();run(a.output,a.reference_trace)
