"""State-based drive-cap scope audit; no native force-readback claim."""
import argparse,json,math
from pathlib import Path
import numpy as np

NAMES=['left_stick_x','left_stick_y','right_stick_x','right_stick_y']
def read(path):return [json.loads(line) for line in path.read_text().splitlines()]
def run(root,output):
 manifest=json.loads((root/'resources_a2/robotwin/full_controls/manifest.json').read_text())
 dynamics={r['name']:dict(r) for r in manifest['joint_dynamics']}
 for name in NAMES:dynamics[name]['damping']+=manifest['backend_options']['robotwin']['joint_friction_params'][name]['viscous']['value']
 def demand(q,v,name):
  d=dynamics[name];return abs(d['stiffness']*(q-d['target'])+d['damping']*v)
 def summarize(label,values,method):
  return {'case':label,'method':method,'joints':{n:{'sampled_demand_peak':max(v),'force_limit':dynamics[n]['force_limit'],'sample_count':len(v),'samples_at_or_above_cap_estimate':sum(x>=dynamics[n]['force_limit'] for x in v)} for n,v in values.items() if v}}
 result={'scope':'Original caps retained. Values are state-based estimates, not internal substep/native constraint-force readback. Below-cap samples do not rule out unsampled solver saturation. Units: Nm for tilt, N for click. Constant click qf preload is outside drive cap.', 'cases':[]}
 for label in ['s0_d0_v8','new_static960','new_shake240']:
  folder=root/'calibration_a2_v3'/label;rows=read(folder/'trace.jsonl');values={n:[] for n in NAMES}
  for row in rows:
   for i,n in enumerate(NAMES):values[n].append(demand(row['tilt_q_rad'][i],row['tilt_qvel_rad_s'][i],n))
  result['cases'].append(summarize('calibration/'+label,values,'Recorded q and qvel at whole-step boundaries'))
 for trace in sorted((root/'frozen_acceptance/cone').glob('*/trace.jsonl')):
  side=trace.parent.name.split('_')[0];names=[side+'_stick_x',side+'_stick_y'];values={n:[] for n in names}
  for row in read(trace):
   for i,n in enumerate(names):values[n].append(demand(row['q'][n],row['tilt_qvel_rad_s'][i],n))
  result['cases'].append(summarize('cone/'+trace.parent.name,values,'Recorded q and qvel; production drive policy, original2.910747N horizontal loading'))
 for group in ['T1','T2']:
  for trace in sorted((root/'frozen_acceptance'/group).glob('*/trace.jsonl')):
   rows=read(trace);name=trace.parent.name.split('_')[0]+'_stick_click';values={name:[]}
   for a,b in zip(rows,rows[1:]):values[name].append(demand(b['q_m'],(b['q_m']-a['q_m'])/(b['time_s']-a['time_s']),name))
   result['cases'].append(summarize(group+'/'+trace.parent.name,values,'Click q, whole-step finite-difference qvel; tilt drive overridden by frozen holding fixture, not estimated from unavailable per-axis state'))
 for trace in sorted((root/'frozen_acceptance/T3').glob('*/trace.jsonl')):
  rows=read(trace);side=trace.parent.name.split('_')[0];name=side+'_stick_x';bounds=[];click=side+'_stick_click';values={click:[]}
  for a,b in zip(rows,rows[1:]):
   qa=np.array(a['cap_pose'][3:]);qb=np.array(b['cap_pose'][3:]);cosine=float(np.clip(abs(qa@qb/np.linalg.norm(qa)/np.linalg.norm(qb)),0,1));omega=2*math.acos(cosine)/.004
   bounds.append(dynamics[name]['stiffness']*math.radians(b['angle_deg'])+dynamics[name]['damping']*omega)
   values[click].append(demand(b['q_m'],(b['q_m']-a['q_m'])/.004,click))
  row=summarize('T3/'+trace.parent.name,values,'Click finite-difference qvel; individual tilt coordinates not recorded')
  row['tilt_conservative_sampled_bound_Nm']={'peak':max(bounds),'cap':dynamics[name]['force_limit'],'samples_at_or_above_cap_bound':sum(x>=dynamics[name]['force_limit'] for x in bounds),'method':'K*total tilt + D*quaternion angular speed; per-axis bound for orthogonal2-axis chain over sampled interval, not actual native torque'};result['cases'].append(row)
 for trace in sorted((root/'frozen_acceptance/T4_candidate64').glob('*/trace.jsonl')):
  rows=read(trace);values={n:[] for n in dynamics}
  for a,b in zip(rows,rows[1:]):
   dt=(b['step']-a['step'])*.004
   if dt<=0:continue
   for n in values:values[n].append(demand(b['joints'][n],(b['joints'][n]-a['joints'][n])/dt,n))
  result['cases'].append(summarize('T4/'+trace.parent.name,values,'Saved20-joint q, whole-step finite-difference qvel; original production drives'))
 result['unavailable']='T1/T2 individual tilt q/qvel and archived stress drive-force readback not recorded; do not invent native saturation observations.'
 output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'cases':len(result['cases']),'estimated_above_cap_cases':[c['case'] for c in result['cases'] if any(x['samples_at_or_above_cap_estimate'] for x in c['joints'].values())]}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.root,a.output)
