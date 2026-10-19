"""Freeze a previously executed Guide target sequence and common world samples."""
import argparse
import json
from pathlib import Path
import numpy as np
from xbox_gamepad_physics.acceptance.cases import load_suite
p=argparse.ArgumentParser();p.add_argument('--trace',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
suite=load_suite();case=suite.case('Guide')
rows=[json.loads(line) for line in a.trace.read_text().splitlines()]
sequence=[{'step':r['step'],'target_m':r['probe']['target_m'],'phase':r['probe']['phase'],
 'phase_age_s':r['probe']['phase_age_s'],'stroke_m':r['probe']['stroke_m']} for r in rows]
record={'suite_id':suite.suite_id,'case_id':'Guide','dt_s':.004,'settings':suite.settings,
 'root_pose':[*case.root_pose.position_m,*case.root_pose.orientation_wxyz], 'plan':dict(case.plan),
 'source':'Unmodified ruling1 SDF0.5 Guide target sequence; diagnostic replay, not a new scored use case',
 'sequence':sequence}
(a.output/'targets.json').write_text(json.dumps(record,indent=2)+'\n')
center=np.asarray(case.plan['point_m']);xy=[];labels=[]
for x in np.linspace(-.003,.003,9):
 for y in np.linspace(-.003,.003,9):xy.append(center[:2]+[x,y]);labels.append('guide_cap')
for r in [.0035,.004,.0045,.005,.006]:
 for theta in np.linspace(0,2*np.pi,16,endpoint=False):xy.append(center[:2]+r*np.array([np.cos(theta),np.sin(theta)]));labels.append('recess_edge')
z=np.linspace(center[2]-.0025,center[2]+.0025,201)
world=np.asarray([[[x,y,v] for v in z] for x,y in xy],dtype=np.float32)
np.savez_compressed(a.output/'sample_points.npz',world_m=world,xy_m=np.asarray(xy),z_m=z,regions=np.asarray(labels))
(a.output/'sample_plan.json').write_text(json.dumps({'columns':len(xy),'z_per_column':len(z),'points':int(world.size/3),
 'vertical_pitch_m':float(z[1]-z[0]),'guide_cap_xy_halfwidth_m':.003,'recess_ring_radii_m':[.0035,.004,.0045,.005,.006],
 'reference_center_m':center.tolist(),'coordinate_frame':'same world frame for both engines; neutral q only'},indent=2)+'\n')
print(json.dumps({'target_steps':len(sequence),'sample_points':int(world.size/3)}))
