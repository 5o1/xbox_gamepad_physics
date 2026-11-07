"""Prespecified mechanism controls after no eligible a1 friction candidate."""
import json,argparse
from pathlib import Path
from unittest.mock import patch
from experiments.robotwin.candidate_calibration import trial,configuration,save

def run(root,resources,old):
 protocol={'reason':'42 predeclared candidates failed independent shake eligibility; no selection. Isolate distance contribution at explicit zero effort/viscosity; holdouts are not used for another tuning sweep.','conditions':['zero_distance_train480','zero_no_distance_train480','old_static960','zero_static960','old_shake240','zero_shake240'],'all_three_new_friction_values':0,'production_policy_changed':False}
 out=root/'mechanism_followup';save(out/'registration.json',protocol);manifest=resources/'robotwin/full_controls/manifest.json';original=manifest.read_bytes()
 try:
  m=json.loads(original);m['backend_options']['robotwin'].update(configuration(0,0,0,root/'CALIBRATION_PROTOCOL_V2.json')['backend_options']['robotwin']);manifest.write_text(json.dumps(m,indent=2)+'\n')
  summaries={}
  s,_=trial(resources,out/'zero_distance_train480',480,4,True);summaries['zero_distance_train480']=s
  with patch('xbox_gamepad_physics.robotwin.mappings.attach_shaft_limits',return_value=([],[])):
   s,_=trial(resources,out/'zero_no_distance_train480',480,4,True);summaries['zero_no_distance_train480']=s
  for name,hz,dur,shake in [('static960',960,3,False),('shake240',240,4,True)]:
   s,_=trial(old,out/('old_'+name),hz,dur,shake,True);summaries['old_'+name]=s
   s,_=trial(resources,out/('zero_'+name),hz,dur,shake);summaries['zero_'+name]=s
  save(out/'summary.json',summaries)
 finally:manifest.write_bytes(original)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--resources',type=Path,required=True);p.add_argument('--old',type=Path,required=True);a=p.parse_args();run(a.root,a.resources.resolve(),a.old.resolve())
