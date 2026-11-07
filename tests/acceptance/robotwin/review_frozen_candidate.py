"""Recompute candidate acceptance from raw traces, not saved pass flags."""
import argparse,json,math,hashlib
from pathlib import Path
from tests.acceptance import load_suite
from tests.acceptance.scoring import score_case

def read(path):return [json.loads(l) for l in path.read_text().splitlines()]
def run(root,output=None):
 out=root/'frozen_acceptance';result={'scope':'Original criteria under explicit64/16 review policy; not production adoption','T1':[],'T2':[],'cone':[],'T3':[],'T4':{}}
 for side in ['left','right']:
  for angle in [0,12,20]:
   rows=read(out/'T1'/f'{side}_{angle}/trace.jsonl');loading=[r for r in rows if r['loading']];cross=lambda v:next((r['applied_force_n'] for r in loading if r['signal']>=v),None);a,b,c=[cross(v) for v in [.05,.5,.95]];low=max(max(r['signal'],r['raw_fraction']) for r in rows if r['applied_force_n']<.9*7.4/r['cosine']);expected=7.4/math.cos(math.radians(angle));passed=a is not None and b is not None and c is not None and c-a<=1 and abs(b/expected-1)<=.1 and low<=.05 and max(rows[-1]['signal'],rows[-1]['raw_fraction'])<=.05 and max(abs(r['shaft_angle_deg']-angle) for r in rows)<=.5;result['T1'].append({'side':side,'angle':angle,'passed':passed,'lowmax':low,'window':c-a if c is not None and a is not None else None})
  for multiple in [.5,.8,.95,1.1,1.3,1.6]:
   rows=read(out/'T2'/f'{side}_{multiple}/trace.jsonl')[-125:];passed=max(max(r['signal'],r['raw_fraction']) for r in rows)<=.05 if multiple<=.95 else min(min(r['signal'],r['raw_fraction']) for r in rows)>=.95;result['T2'].append({'side':side,'multiple':multiple,'passed':passed})
  for direction in ['diagonal45','positive_x','positive_y']:
   rows=read(out/'cone'/f'{side}_{direction}/trace.jsonl');hold=[r for r in rows if .8-1e-9<=r['time_s']<=1+1e-9];release=[r for r in rows if r['time_s']>=1.8-1e-9];passed=max(r['angle_deg'] for r in hold)<=23.1 and (direction=='diagonal45' or min(r['angle_deg'] for r in hold)>=22.9) and max(r['angle_deg'] for r in release)<=.1 and max(abs(v) for r in release for v in r['tilt_qvel_rad_s'])<=.01;result['cone'].append({'side':side,'direction':direction,'passed':passed})
  for force in [1,2,4,6,8.14]:
   rows=read(out/'T3'/f'{side}_{force}/trace.jsonl');hold=[r for r in rows if r['phase']=='hold'];valid=min(r['angle_deg'] for r in hold)>=1;passed=valid and (max(r['signal'] for r in hold)<=.05 if force<6.66 else min(r['signal'] for r in hold[-125:])>=.95) and rows[-1]['signal']<=.05;result['T3'].append({'side':side,'force':force,'valid':valid,'passed':passed})
 suite=load_suite()
 for policy in ['T4_candidate64','T4_default10']:
  scores=[score_case(suite,case,read(out/policy/case.case_id/'trace.jsonl')) for case in suite.cases];result['T4'][policy]={'passed':sum(s['physics_passed'] for s in scores),'regressions':[s['case'] for s,c in zip(scores,suite.cases) if c.baseline['passed'] and not s['physics_passed']],'failures':[s['case'] for s in scores if not s['physics_passed']]}
 config=hashlib.sha256((root/'CANDIDATE_CALIBRATION.json').read_bytes()).hexdigest();result['frozen_config_sha256']=config;result['all_explicit_original_criteria_under_candidate_policy']=all(r['passed'] for key in ['T1','T2','cone','T3'] for r in result[key]) and not result['T4']['T4_candidate64']['regressions'];result['extra_stress_failures_retained']='a2_boundary_frozen/results.json';result['holdout_differences_retained']='CANDIDATE_RECEIPT.json';(output or root/'RAW_REVIEW.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path);a=p.parse_args();run(a.root,a.output)
