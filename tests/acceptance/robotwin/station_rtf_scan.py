"""Serial experiment launcher, archived with raw evidence rather than installed."""
import argparse,json,os,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--python',required=True);a=p.parse_args()
r=a.root; baseline=json.loads((r/'acceptance-default/summary.json').read_text())['results'];sleep=json.loads((r/'sleep-0.5-full/summary.json').read_text())['results']
expected={'T1':6,'T2':12,'cone':6,'T3v2':10,'T4':23}
def accepted(data):
 return all(data[k]['passed']>=n and data[k]['executed']==baseline[k]['executed'] for k,n in expected.items()) and set(baseline['T4']['passed_cases'])<=set(data['T4']['passed_cases'])
use_sleep=accepted(sleep)
extra=['--sleep-threshold','0.5'] if use_sleep else []
state=dict(started_monotonic=time.monotonic(),sleep_threshold=0.5 if use_sleep else None,groups=[])
(r/'grid-state.json').write_text(json.dumps(state,indent=2)+'\n')
for pos in [24,32,48,64]:
 for vel in [1,2,4]:
  name=f'grid-{pos}-{vel}';start=time.monotonic()
  cmd=['taskset','-c','8',a.python,'-m','tests.acceptance.robotwin.station_rtf','--suite','full','--iterations',str(pos),str(vel),*extra,'--output',str(r/(name+'-acceptance'))]
  with (r/(name+'-acceptance.log')).open('w') as log: subprocess.run(cmd,cwd=r/'support',check=True,stdout=log,stderr=subprocess.STDOUT)
  physics=json.loads((r/(name+'-acceptance')/'summary.json').read_text())['results']
  perf={}
  for condition in ['static','active','contact']:
   output=r/(name+'-'+condition)
   cmd=['taskset','-c','8',a.python,str(r/'code/experiments/robotwin/station_rtf/benchmark.py'),'--aq-probe',str(r/'support/reports/2026-11-09-realtime-input-lag/engine_probe.py'),'--condition',condition,'--iterations',str(pos),str(vel),*extra,'--output',str(output)]
   with (r/(name+'-'+condition+'.log')).open('w') as log: subprocess.run(cmd,cwd=r/'support',check=True,stdout=log,stderr=subprocess.STDOUT)
   perf[condition]=json.loads((output/'summary.json').read_text())['distribution']
  ok=accepted(physics)
  row=dict(position=pos,velocity=vel,physics_passed=ok,performance_passed=all(d['total']['p95_us']<=800 and d['total']['median_us']<=800 for d in perf.values()),acceptance={k:[v['passed'],v['executed']] for k,v in physics.items()},regressed_t4=sorted(set(baseline['T4']['passed_cases'])-set(physics['T4']['passed_cases'])),perf=perf,elapsed_s=time.monotonic()-start)
  state['groups'].append(row);state['feasible']=ok and row['performance_passed'];(r/'grid-state.json').write_text(json.dumps(state,indent=2)+'\n');print(json.dumps(row),flush=True)
  if state['feasible']: raise SystemExit(0)
state['finished']=True;(r/'grid-state.json').write_text(json.dumps(state,indent=2)+'\n')
