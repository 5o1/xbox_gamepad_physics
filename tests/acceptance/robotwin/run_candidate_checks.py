"""Collect original criteria against an independently frozen candidate."""
import argparse,json,os,hashlib
from pathlib import Path
from unittest.mock import patch
from . import executor,stick_click,stick_cone_production,stick_click_t3_point_v2
from .run_suite import cpu_scene

def run(resources,out,test,config,model='new',public_resources=False,representative=False):
 os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(resources.resolve());out.mkdir(parents=True,exist_ok=True);before=hashlib.sha256(config.read_bytes()).hexdigest()
 os.environ['XGP_ACCEPTANCE_PUBLIC_RESOURCES']='1' if public_resources else '0'
 receipt={'config_sha256_before':before,'resources':str(resources.resolve()),'test':test,'model':model,'scene':'CPU-only; inherited global config; per-art numerical policy from candidate options only'}
 receipt.update(public_resource_resolution=public_resources,representative_subset=representative)
 (out/'candidate_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 with patch.object(executor,'create_scene',side_effect=cpu_scene):
  if test=='T1':passed=stick_click.t1(out,stop_on_failure=False,cases=[('right',20)] if representative else None)
  elif test=='T2':passed=stick_click.t2(out)
  elif test=='cone':passed=stick_cone_production.run(out,cases=[('right','diagonal45'),('left','positive_x')] if representative else None)
  else:
   rows=stick_click_t3_point_v2.run(resources,out,model,cases=[('right',6),('right',8.14)] if representative else None);passed=all(r['physics_passed'] is True for r in rows)
 receipt['config_sha256_after']=hashlib.sha256(config.read_bytes()).hexdigest();receipt['config_unchanged']=receipt['config_sha256_after']==before;receipt['passed']=passed;(out/'candidate_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));return not passed
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--test',choices=['T1','T2','cone','T3'],required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--model',default='new');p.add_argument('--public-resources',action='store_true',help='Resolve stamped DAG resources through the normal public loader.');p.add_argument('--representative',action='store_true',help='Run only the declared propagation-check subset; original criteria unchanged.');a=p.parse_args();raise SystemExit(run(a.resources,a.output,a.test,a.config,a.model,a.public_resources,a.representative))
