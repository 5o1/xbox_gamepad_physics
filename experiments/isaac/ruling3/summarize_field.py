"""Extract vertical zero crossings from native field samples, retaining missing roots."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--inputs',type=Path,required=True);a=p.parse_args()
field=np.load(a.directory/'cooked_sdf.npz');plan=np.load(a.inputs/'sample_points.npz')
world=plan['world_m'];dist=field['gradient_xyz_distance_w'][:,:,-1].reshape(-1,*world.shape[:2])
assert np.array_equal(field['world_m'],world.reshape(-1,3))
with (a.directory/'ZERO_CROSSINGS.csv').open('w',newline='') as output:
 writer=csv.DictWriter(output,fieldnames=['shape','link','column','region','x_m','y_m','highest_exit_zero_z_m','exit_crossing_count'])
 writer.writeheader()
 for shape,values in enumerate(dist):
  for col,d in enumerate(values):
   z=world[col,:,2];indices=np.where((d[:-1]<=0)&(d[1:]>=0)&(d[:-1]!=d[1:]))[0]
   roots=[float(z[i]+(z[i+1]-z[i])*(-d[i])/(d[i+1]-d[i])) for i in indices]
   writer.writerow({'shape':shape,'link':field['links'][shape],'column':col,'region':plan['regions'][col],
    'x_m':float(world[col,0,0]),'y_m':float(world[col,0,1]),'highest_exit_zero_z_m':max(roots) if roots else None,'exit_crossing_count':len(roots)})
(a.directory/'field_summary.json').write_text(json.dumps({'query_points_per_shape':world.shape[0]*world.shape[1],
 'shapes':len(dist),'same_world_points_as_plan':True,'all_finite':bool(np.isfinite(dist).all()),
 'vertical_pitch_m':float(world[0,1,2]-world[0,0,2]),'interpolation':'linear on 25 micrometre vertical samples',
 'missing_zero_semantics':'blank when the finite sampled vertical segment has no negative-to-positive crossing; not a missing SDF shape'},indent=2)+'\n')
