"""Extract diagnostic events without changing acceptance thresholds or scoring."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
rows=[json.loads(line) for line in (a.directory/'trajectory.jsonl').read_text().splitlines()]
columns=['step','phase','actual_s_m','q_m','guide_separation_m','guide_normal_x','guide_normal_y','guide_normal_z','shell_separation_m']
with (a.directory/'QS_CONTACT.csv').open('w',newline='') as output:
 writer=csv.DictWriter(output,fieldnames=columns);writer.writeheader()
 for row in rows:
  selected={link:min((c for c in row['contacts'] if c['link']==link),key=lambda c:c['separation_m'],default=None) for link in ['guide','controller_body']}
  guide,shell=selected['guide'],selected['controller_body']
  writer.writerow({**{k:row[k] for k in ['step','phase','actual_s_m','q_m']},
    'guide_separation_m':guide['separation_m'] if guide else None,
    **dict(zip(['guide_normal_x','guide_normal_y','guide_normal_z'],guide['normal'] if guide else [None]*3)),
    'shell_separation_m':shell['separation_m'] if shell else None})

def event(predicate):
 row=next((r for r in rows if predicate(r)),None)
 return {k:row[k] for k in ['step','phase','actual_s_m','q_m']} if row else None
summary={'steps':len(rows),'guide_motion_above_1um':event(lambda r:abs(r['q_m'])>1e-6),
 'motion_threshold_basis':'1 micrometre diagnostic reporting threshold; no change to scoring',
 'first_guide_contact':event(lambda r:any(c['link']=='guide' for c in r['contacts'])),
 'first_shell_contact':event(lambda r:any(c['link']=='controller_body' for c in r['contacts'])),
 'maximum_q_m':max(r['q_m'] for r in rows),'minimum_separation_m':{link:min((c['separation_m'] for r in rows for c in r['contacts'] if c['link']==link),default=None) for link in ['guide','controller_body']},
 'hold_last125_q_range_m':[min(r['q_m'] for r in [r for r in rows if r['phase']=='hold'][-125:]),max(r['q_m'] for r in [r for r in rows if r['phase']=='hold'][-125:])],
 'no_contact_distance_semantics':'CSV blank means no native contact point, not zero clearance'}
(a.directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary))
