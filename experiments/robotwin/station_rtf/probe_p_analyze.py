"""Summarize this diagnostic's fresh raw data; never changes test criteria."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from tests.acceptance import load_suite

p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);a=p.parse_args()
all_rows=[];details=[];suite=load_suite()
for f in sorted(a.raw.glob('final-r1-iters-*/summary.json')):
    data=json.loads(f.read_text())
    for row in data['results']:
        rec={k:row.get(k) for k in ['case','method','dt_s','target_min','target_max','target_threshold','passed','return_time_s','max_joint_displacement','max_travel_fraction']}
        rec.update(iterations='/'.join(map(str,data['iterations'])),termination=json.dumps(row.get('termination'),ensure_ascii=False),contact_pairs=';'.join(row['contact_pairs']),misfires=json.dumps(row.get('misfires',{})))
        all_rows.append(rec)
        if row['method']!='T4':continue
        case=suite.case(row['case']);d=np.array(case.plan['direction']);d=d/np.linalg.norm(d)
        trace=f.parent/'T4'/row['case']/'trace.jsonl'
        samples=[json.loads(line) for line in trace.read_text().splitlines()]
        stable=[r for r in samples if r['probe']['phase']=='hold'][-125:]
        origin=np.array(case.plan['start_m']);lateral=[];forces={}
        for r in stable:
            off=np.array(r['probe']['pose'][:3])-origin
            lateral.append(float(np.linalg.norm(off-d*(off@d))))
            per={}
            for contact in r['contacts']:
                other=next(n for n in contact['bodies'] if n!='test_ball')
                axial=sum(abs(float(np.array(q['impulse_ns'])@d))/data['dt_s'] for q in contact['points'])
                per[other]=per.get(other,0.)+axial
            for key in set(forces)|set(per):
                if key not in forces:forces[key]=[0.]*(len(lateral)-1)
                forces[key].append(per.get(key,0.))
        details.append(dict(case=row['case'],iterations=data['iterations'],dt_s=data['dt_s'],lateral_max_m=max(lateral),lateral_min_m=min(lateral),mean_absolute_axial_contact_force_n={k:float(np.mean(v)) for k,v in forces.items()},nonzero_axial_contact_steps={k:sum(x>1e-6 for x in v) for k,v in forces.items()},hold_force_norm_max_n=max(float(np.linalg.norm(r['probe']['force_n'])) for r in stable),termination=row['termination']))
with (a.raw/'results.csv').open('w',newline='') as out:
    w=csv.DictWriter(out,fieldnames=list(all_rows[0]));w.writeheader();w.writerows(all_rows)
(a.raw/'aggregate.json').write_text(json.dumps(dict(results=all_rows,t4_contact_details=details),indent=2)+'\n')
for f in sorted(a.raw.glob('final-r1-iters-*/summary.json')):
    d=json.loads(f.read_text());print(f.parent.name,[(m,sum(r['passed'] for r in d['results'] if r['method']==m),sum(r['method']==m for r in d['results'])) for m in sorted(set(r['method'] for r in d['results']))])
print('rows',len(all_rows))
