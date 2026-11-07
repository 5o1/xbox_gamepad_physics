"""Owner ruling4 diagnostic snapshots; never modify production resources."""
from pathlib import Path
import os, json, shutil, hashlib, argparse
import xml.etree.ElementTree as ET
import numpy as np
from tests.acceptance.robotwin.stick_click import setup, shaft, sample, save
from experiments.robotwin.joint_readback import policy
from tests.acceptance.records import ResultSink

HERE=Path(__file__).resolve().parent

def swap(snapshot, donor):
    rel=Path('robotwin/full_controls/manifest.json')
    a=json.loads((snapshot/rel).read_text()); b=json.loads((donor/rel).read_text())
    click={'left_stick_click','right_stick_click'}
    records={r['name']:r for r in b['joint_dynamics']}
    for i,r in enumerate(a['joint_dynamics']):
        if r['name'] in click:a['joint_dynamics'][i]=records[r['name']]
    save(snapshot/rel,a)
    rel=Path('robotwin/full_controls/mobility.urdf')
    ta,tb=ET.parse(snapshot/rel),ET.parse(donor/rel)
    bd={j.get('name'):j for j in tb.findall('joint')}
    for j in ta.findall('joint'):
        if j.get('name') in click:
            j.find('dynamics').attrib.clear(); j.find('dynamics').attrib.update(bd[j.get('name')].find('dynamics').attrib)
    ta.write(snapshot/rel,encoding='utf-8',xml_declaration=True)
    rel=Path('common/xbox_one_s/physical/full_controls.json')
    a=json.loads((snapshot/rel).read_text());b=json.loads((donor/rel).read_text())
    for n in click:a['return_laws'][n]=b['return_laws'][n]
    save(snapshot/rel,a)

def structure(e, snapshot):
    rows=[];offset=0
    for j in e.art.get_active_joints():
        rows.append({'name':j.name,'type':j.type,'dof':j.dof,'qpos_offset':offset,
            'parent':j.get_parent_link().name,'child':j.get_child_link().name,
            'positive_axis_in_child':j.get_pose_in_child().to_transformation_matrix()[:3,0].tolist(),
            'limits':j.get_limits().tolist()})
        offset+=j.dof
    tree=ET.parse(snapshot/'robotwin/full_controls/mobility.urdf')
    return {'total_dof':e.art.dof,'active_joints':rows,'links':[{'name':l.name,'mass_kg':l.mass,'joint_type':l.joint.type} for l in e.art.get_links()],
        'urdf_stick_joints':{j.get('name'):ET.tostring(j,encoding='unicode') for j in tree.findall('joint') if j.get('name').startswith('left_stick')},
        'policy':policy(e)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--new',type=Path,required=True);p.add_argument('--old',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    protocol=HERE/'stick_click_2x2_protocol.json';save(out/'registration.json',{'protocol':json.loads(protocol.read_text()),'sha256':hashlib.sha256(protocol.read_bytes()).hexdigest()})
    inputs={'A_old_chain_old_law':args.old,'B_old_chain_new_law':args.old,'C_new_chain_old_law':args.new,'D_new_chain_new_law':args.new}
    results=[]
    for name,source in inputs.items():
        snapshot=out/'snapshots'/name
        shutil.copytree(source,snapshot)
        if name.startswith('B_'):swap(snapshot,args.new)
        if name.startswith('C_'):swap(snapshot,args.old)
        os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(snapshot)
        e=setup('left'); folder=out/name;save(folder/'structure.json',structure(e,snapshot)); rows=[]
        sink=ResultSink(folder/'trace.jsonl')
        try:
            for i in range(751):
                force=12*i/750;axis,center=shaft(e);e.cap.add_force_at_point(force*axis,center,mode='force');e.scene.step()
                row={**sample(e),'step':i,'force_n':force,'qvel_m_s':e.gamepad.joint_velocity('left_stick_click')};rows.append(row);sink.write(row)
        finally:sink.close()
        result={'condition':name,'max_fraction':max(r['raw_fraction'] for r in rows),'final_q_m':rows[-1]['q_m'],'first_half_force_n':next((r['force_n'] for r in rows if r['raw_fraction']>=.5),None)}
        results.append(result);save(out/'results.json',{'scans':results});print(json.dumps(result),flush=True)
    os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(out/'snapshots/D_new_chain_new_law')
    e=setup('left');j=e.joints['left_stick_click'];before=policy(e);j.set_drive_properties(18500,12.043255373859676,force_limit=10.4,mode='force');j.set_drive_target(.0002)
    sink=ResultSink(out/'direct_drive/trace.jsonl');rows=[]
    try:
        for i in range(250):
            e.scene.step();row={**sample(e),'step':i,'qvel_m_s':e.gamepad.joint_velocity('left_stick_click')};rows.append(row);sink.write(row)
    finally:sink.close()
    direct={'target_m':.0002,'before':before,'after':policy(e),'final':rows[-1],'max_fraction':max(r['raw_fraction'] for r in rows),'follows_target':abs(rows[-1]['q_m']-.0002)<=.00001}
    save(out/'direct_drive/results.json',direct);save(out/'results.json',{'scans':results,'direct_drive':direct});print(json.dumps({'direct_follows':direct['follows_target'],'final_q_m':rows[-1]['q_m']}),flush=True)
if __name__=='__main__':main()
