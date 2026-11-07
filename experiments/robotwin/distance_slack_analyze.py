"""Archive small summaries; full per-step evidence stays on the GPU node."""
import argparse,json,csv,hashlib
from pathlib import Path
import numpy as np

def main(root):
 records=[]
 for run in ['run','run_fixed']:
  p=root/run/'results.json';d=json.loads(p.read_text())
  for row in d['results']:row['run']=run;records.append(row)
 fields=['condition','side','commanded_angle_deg','variant','fixed_click','native_dof','steps','min_gap_whole_run_m','steady_gap_min_m','steady_gap_max_m','steady_fraction_mean','steady_angle_mean_deg']
 with (root/'RESULTS.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r[k] for k in fields} for r in records)
 geometry=[];manifest=[]
 with (root/'SAMPLED_TRACE.jsonl').open('w') as sample:
  for r in records:
   p=root/r['run']/r['condition']/'trace.jsonl';rows=[json.loads(l) for l in p.read_text().splitlines()];res=[]
   for row in rows:
    for stage in ['before','after']:
     x=row[stage]
     if x['distance_component_readback_m'] is not None:res.append(abs(x['d_m']-x['distance_component_readback_m']))
   for i in sorted(set([0,1,2,3,4,249,250,500,750,1000,1250,1500,len(rows)-1])):
    sample.write(json.dumps({'condition':r['condition'],'sample_only':True,'row':rows[i]})+'\n')
   x=r['final'];geometry.append({'condition':r['condition'],'native_parent':x['native_parent'],'parent_local_anchor_m':x['parent_local_anchor_m'],'child_local_anchor_m':x['child_local_anchor_m'],'parent_radius_m':x['parent_radius_m'],'child_radius_m':x['child_radius_m'],'shaft_direction_world':x['shaft_direction_world'],'min_gap_before_after_m':min(row[stage]['gap_m'] for row in rows for stage in ['before','after']),'max_d_before_after_m':max(row[stage]['d_m'] for row in rows for stage in ['before','after']),'final_d_m':x['d_m'],'commanded_d_max_m':x['d_max_m'],'dmax_native_getter':None,'dmax_reason':'Explicit command known; no max-distance getter in this Python binding.','max_native_vs_recomputed_distance_error_m':max(res) if res else None})
   manifest.append({'relative_path':str(p.relative_to(root)),'bytes':p.stat().st_size,'rows':len(rows),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 pairs=[]
 for r in records:
  if r['variant']!='with_distance':continue
  off=next(x for x in records if x['side']==r['side'] and x['commanded_angle_deg']==r['commanded_angle_deg'] and x['fixed_click']==r['fixed_click'] and x['variant']=='without_distance')
  onrows=[json.loads(l) for l in (root/r['run']/r['condition']/'trace.jsonl').read_text().splitlines()];offrows=[json.loads(l) for l in (root/off['run']/off['condition']/'trace.jsonl').read_text().splitlines()]
  delta=np.array([a['after']['incoming_click_frame_wrench'][0]-b['after']['incoming_click_frame_wrench'][0] for a,b in zip(onrows,offrows)])
  pairs.append({'condition':r['condition'],'frame':'incoming joint frame X; fixed-joint controls are not a prismatic generalized-force measurement','steady_net_force_difference_mean_n':float(delta[-250:].mean()),'steady_net_force_difference_min_n':float(delta[-250:].min()),'steady_net_force_difference_max_n':float(delta[-250:].max()),'whole_run_net_difference_absmax_n':float(abs(delta).max()),'not_isolated_distance_force':True})
 (root/'GEOMETRY.json').write_text(json.dumps(geometry,indent=2)+'\n');(root/'FORCE_DIFFERENCE.json').write_text(json.dumps(pairs,indent=2)+'\n');(root/'TRACE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print(json.dumps({'conditions':len(records),'recorded_steps':sum(x['steps'] for x in records),'trace_bytes':sum(x['bytes'] for x in manifest),'force20':[x for x in pairs if '_20_' in x['condition']],'geometry20':[x for x in geometry if x['condition'] in ['left_20_with_distance','right_20_with_distance']]},indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();main(a.root)
