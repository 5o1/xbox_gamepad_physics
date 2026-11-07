"""Native distance-anchor readback and no-load verification for ruling9."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
from tests.acceptance.robotwin.stick_click import setup,sample,save
from tests.acceptance.records import ResultSink

PROTOCOL=Path(__file__).with_name('click_anchor_protocol.json')
def verify(e):
 records=[];joints=e.joints;links=e.links
 for conn in e.gamepad._native_shaft_limits:
  child=next(l for l in links.values() if l.entity==conn.entity)
  side='left' if child.name.startswith('left') else 'right'
  click=joints[side+'_stick_click'];cp=click.get_child_link();tx=joints[side+'_stick_x'].get_parent_link();parent=conn.get_parent()
  a=(parent.entity_pose*conn.get_pose_in_parent()).p.astype(float);b=(child.entity_pose*conn.get_pose_in_child()).p.astype(float)
  axis=(cp.entity_pose*click.get_pose_in_child()).to_transformation_matrix()[:3,0].astype(float)
  shifts=[]
  for q in [0,.0002,.0004]:
   pa=a+(q*axis if parent==cp else 0);pb=b+q*axis
   shifts.append({'common_click_translation_m':q,'derived_distance_m':float(np.linalg.norm(pb-pa))})
  records.append({'side':side,'native_parent':parent.name,'native_child_entity':conn.entity.name,
    'click_child':cp.name,'tilt_x_parent':tx.name,'parent_is_click_child':parent==cp,
    'parent_is_tilt_x_parent':parent==tx,'parent_is_body':parent==links['controller_body'],
    'pose_in_parent':conn.get_pose_in_parent().to_transformation_matrix().tolist(),
    'pose_in_child':conn.get_pose_in_child().to_transformation_matrix().tolist(),
    'parent_anchor_radius_m':float(np.linalg.norm(a-parent.entity_pose.p)),
    'child_anchor_radius_m':float(np.linalg.norm(b-child.entity_pose.p)),
    'geometric_common_translation_sweep':shifts,'max_distance_change_m':max(x['derived_distance_m'] for x in shifts)-min(x['derived_distance_m'] for x in shifts)})
 return records

def main(out):
 p=json.loads(PROTOCOL.read_text());out.mkdir(parents=True,exist_ok=True);save(out/'registration.json',{'protocol':p,'sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()});results=[]
 for side in p['sides']:
  for angle in p['angles_deg']:
   e=setup(side,angle);folder=out/(side+'_'+str(angle));save(folder/'native_connections.json',verify(e));sink=ResultSink(folder/'trace.jsonl');rows=[]
   try:
    for i in range(1500):
     e.scene.step();row={**sample(e),'step':i,'qvel_m_s':e.gamepad.joint_velocity(side+'_stick_click')};rows.append(row);sink.write(row)
   finally:sink.close()
   result={'side':side,'angle_deg':angle,'max_fraction':max(r['raw_fraction'] for r in rows),'final_fraction':rows[-1]['raw_fraction'],'actual_angle_deg':rows[-1]['shaft_angle_deg'],'passed':max(r['raw_fraction'] for r in rows)<=.05,'native_connections':verify(e)};results.append(result);save(out/'results.json',{'results':results,'passed':all(r['passed'] for r in results)});print(json.dumps({k:v for k,v in result.items() if k!='native_connections'}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.output)
