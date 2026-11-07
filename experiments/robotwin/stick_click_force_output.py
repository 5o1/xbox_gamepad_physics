"""Ruling5 read-only production tracing and diagnostic native-force scans."""
import os,json,argparse,hashlib
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
import numpy as np
from tests.acceptance.robotwin.stick_click import setup,shaft,sample,save
from experiments.robotwin.joint_readback import policy
from tests.acceptance.records import ResultSink
from xbox_gamepad_physics.robotwin import loader

HERE=Path(__file__).resolve().parent
class JointProxy:
    def __init__(self,native,records):self.native=native;self.records=records
    def __getattr__(self,n):return getattr(self.native,n)
    def set_drive_properties(self,*args,**kwargs):
        self.records.append({'joint':self.native.name,'method':'set_drive_properties','args':list(args),'kwargs':kwargs})
        return self.native.set_drive_properties(*args,**kwargs)
    def set_drive_target(self,*args,**kwargs):
        self.records.append({'joint':self.native.name,'method':'set_drive_target','args':list(args),'kwargs':kwargs})
        return self.native.set_drive_target(*args,**kwargs)
class ArtProxy:
    def __init__(self,native,records):self.native=native;self.records=records
    def __getattr__(self,n):return getattr(self.native,n)
    def get_active_joints(self):return [JointProxy(j,self.records) for j in self.native.get_active_joints()]

def run(resources,out):
    os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(resources.resolve())
    out.mkdir(parents=True,exist_ok=True);p=HERE/'stick_click_force_output_protocol.json';protocol=json.loads(p.read_text())
    save(out/'registration.json',{'protocol':protocol,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    physical=json.loads((resources/'common/xbox_one_s/physical/full_controls.json').read_text())
    manifest=json.loads((resources/'robotwin/full_controls/manifest.json').read_text())
    xml=ET.parse(resources/'robotwin/full_controls/mobility.urdf');results=[]
    original=loader._configure_joints
    for condition in protocol['conditions']:
        calls=[];override_calls=[]
        def trace_config(native,*args,**kwargs):
            wrapper=original(ArtProxy(native,calls),*args,**kwargs)
            wrapper._articulation=native
            joint=next(j for j in native.get_active_joints() if j.name=='left_stick_click')
            o=condition['overrides']
            if 'stiffness' in o or 'force_limit' in o:
                a=[o.get('stiffness',float(joint.stiffness)),float(joint.damping)]
                k={'force_limit':o.get('force_limit',float(joint.force_limit)),'mode':joint.drive_mode}
                override_calls.append({'method':'set_drive_properties','args':a,'kwargs':k});joint.set_drive_properties(*a,**k)
            if 'target' in o:
                override_calls.append({'method':'set_drive_target','args':[o['target']]});joint.set_drive_target(o['target'])
            return wrapper
        with patch.object(loader,'_configure_joints',side_effect=trace_config):e=setup('left')
        j=e.joints['left_stick_click'];pol=policy(e)['left_stick_click'];child=j.get_child_link()
        links=e.art.get_links();ci=links.index(child);qi=[x.name for x in e.art.get_active_joints()].index(j.name)
        folder=out/condition['name']
        save(folder/'end_to_end.json',{'physical_law':physical['return_laws'][j.name],
            'manifest':next(x for x in manifest['joint_dynamics'] if x['name']==j.name),
            'urdf_fragment':ET.tostring(next(x for x in xml.findall('joint') if x.get('name')==j.name),encoding='unicode'),
            'loader_native_calls':calls,'diagnostic_override_calls':override_calls,'native_policy':pol,
            'link_names':[l.name for l in links],'click_child_link_index_in_get_links':ci,
            'click_child_native_index':getattr(child,'index',None),'click_qpos_index':qi,
            'incoming_wrench_readback':'raw native array; see source_audit for joint-frame [linear,angular] convention',
            'isolated_drive_force_n':None,'missing_reason':'SAPIEN3.0.3 has no exposed isolated drive-force getter.'})
        rows=[];sink=ResultSink(folder/'trace.jsonl')
        try:
            for i in range(751):
                force=12*i/750;axis,center=shaft(e)
                positive=(child.entity_pose*j.get_pose_in_child()).to_transformation_matrix()[:3,0]
                e.cap.add_force_at_point(force*axis,center,mode='force');e.scene.step()
                incoming=e.art.get_link_incoming_joint_forces();qf=e.art.get_qf();state=sample(e);vel=e.gamepad.joint_velocity(j.name)
                elastic=pol['stiffness']*(state['q_m']-pol['target'][0]);raw=-elastic-pol['damping']*vel
                row={**state,'step':i,'force_n':force,'external_projection_n':float((force*axis)@positive),
                    'qvel_m_s':vel,'incoming_link_wrenches_native':incoming.tolist(),
                    'click_child_incoming_wrench_native':incoming[ci].tolist(),
                    'user_generalized_force_native':qf.tolist(),'click_user_qf_n':float(qf[qi]),
                    'isolated_drive_force_n':None,'reference_elastic_restoring_n':elastic,
                    'reference_clipped_drive_n':max(-pol['force_limit'],min(pol['force_limit'],raw)),
                    'reference_minus_measured_incoming_x_n':max(-pol['force_limit'],min(pol['force_limit'],raw))-float(incoming[ci][0])}
                sink.write(row);rows.append(row)
        finally:sink.close()
        results.append({'condition':condition['name'],'policy':pol,'max_fraction':max(x['raw_fraction'] for x in rows),
            'final':rows[-1],'first_half_force_n':next((x['force_n'] for x in rows if x['raw_fraction']>=.5),None),
            'incoming_child_x_range_n':[min(x['click_child_incoming_wrench_native'][0] for x in rows),max(x['click_child_incoming_wrench_native'][0] for x in rows)]})
        save(out/'results.json',{'conditions':results})
        print(json.dumps({'condition':condition['name'],'max_fraction':results[-1]['max_fraction'],'half_force':results[-1]['first_half_force_n'],'incoming_x_range':results[-1]['incoming_child_x_range_n']}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.resources,a.output)
