"""Summarize ruling12 without copying full per-step datasets off the node."""
import argparse,json,csv,hashlib
from pathlib import Path
import numpy as np

def run(root):
 d=json.loads((root/'run/results.json').read_text());table=[];wrenches=[];manifest=[]
 for variant in d['variants']:
  name=variant['variant']
  for r in variant['results']['results']:
   folder=root/'run'/name/(r['side']+'_'+r['direction']);p=folder/'wrench_trace.jsonl';rows=[json.loads(l) for l in p.read_text().splitlines()];steady=rows[449:500];rb=json.loads((folder/'factor_readback.json').read_text());changes=[{'joint':n,'field':k,'before':rb['before'][n][k],'after':v} for n,fields in rb['after'].items() for k,v in fields.items() if rb['before'][n][k]!=v]
   table.append({'variant':name,**r,'policy_changes':changes,'changed_qf_indices':[i for i,(a,b) in enumerate(zip(rb['qf_before'],rb['qf_after'])) if a!=b]})
   for n in steady[0]['tilt_incoming_joint_wrenches']:
    vals=np.array([x['tilt_incoming_joint_wrenches'][n] for x in steady]);wrenches.append({'variant':name,'side':r['side'],'direction':r['direction'],'joint':n,'mean_wrench_in_incoming_joint_frame':vals.mean(0).tolist(),'max_linear_force_norm_n':float(np.linalg.norm(vals[:,:3],axis=1).max()),'max_angular_torque_norm_nm':float(np.linalg.norm(vals[:,3:],axis=1).max()),'not_internal_friction_bound':True})
   for file in [p,folder/'trace.jsonl']:
    manifest.append({'path':str(file.relative_to(root)),'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
 fields=['variant','side','direction','steady_min_deg','steady_max_deg','load_peak_deg','first_peak_deg','first_peak_time_s','release_max_deg','release_max_speed_rad_s','boundary_reached','return_pass','passed']
 with (root/'RESULTS.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r[k] for k in fields} for r in table)
 (root/'READBACK_COMPARISON.json').write_text(json.dumps(table,indent=2)+'\n');(root/'TILT_WRENCH_SUMMARY.json').write_text(json.dumps(wrenches,indent=2)+'\n');(root/'TRACE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print(json.dumps({'conditions':len(table),'recorded_steps':len(table)*750,'trace_bytes':sum(x['bytes'] for x in manifest),'left_diagonal_wrenches':[x for x in wrenches if x['side']=='left' and x['direction']=='diagonal45']},indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();run(a.root)
