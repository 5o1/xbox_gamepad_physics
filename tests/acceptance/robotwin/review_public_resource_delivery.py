"""Public SDF load and physical nonzero signal roundtrip for prepared DAG output."""
import argparse,hashlib,json,os
from pathlib import Path
import numpy as np

def same_physics_input(name,a,b):
 """URDF usage comments are metadata; compare every mechanism XML element."""
 if not name.endswith('.urdf'):return a==b
 import xml.etree.ElementTree as ET
 def tree(e):return (e.tag,dict(e.attrib),[tree(c) for c in e])
 return tree(ET.fromstring(a))==tree(ET.fromstring(b))

def compare_saved(root,reference,public_receipt,candidate_receipt):
 """Compare native policies and exact physics inputs after public loading."""
 import xml.etree.ElementTree as ET
 differences=[]
 fields={'native_drive_K':'K','native_drive_D':'D','effort':'effort','target':'target',
         'native_legacy_coefficient':'legacy','native_friction_params':'new'}
 for name,old in candidate_receipt['joints'].items():
  for a,b in fields.items():
   if old[a]!=public_receipt['native_joints'][name][b]:differences.append([name,a])
 files=['common/xbox_one_s/motion/full_controls.json','robotwin/full_controls/mobility.urdf']
 files += [str(p.relative_to(reference)) for p in (reference/'robotwin/full_controls/collision').rglob('*.obj')]
 file_rows=[{'file':p,'equal':(root/p).read_bytes()==(reference/p).read_bytes(),
             'physical_equal':same_physics_input(p,(root/p).read_bytes(),(reference/p).read_bytes())} for p in files]
 links=ET.parse(root/'robotwin/full_controls/mobility.urdf').getroot().findall('link')
 return {'native_policy_differences':differences,'joint_count':len(public_receipt['native_joints']),
         'iterations_equal':public_receipt['native_iterations']==candidate_receipt['iterations'],
         'qf_equal':public_receipt['native_qf']==candidate_receipt['qf'],
         'files':file_rows,'link_inertials_in_identical_URDF':{l.attrib['name']:ET.tostring(l.find('inertial'),encoding='unicode') for l in links},
         'geometry_mass_inertia_and_neutral_joint_origins_equal':all(row['physical_equal'] for row in file_rows),
         'metadata_note':'Raw legacy coefficient metadata may differ; new-mode loader clears it. Comparison above uses actual native getters on all20 joints.'}

def run(root,reference,output):
 import sapien
 from xbox_gamepad_physics.robotwin import load_into_scene
 from xbox_gamepad_physics.motion import load_motion_contract
 from xbox_gamepad_physics.state import GamepadState,CHANNEL_NAMES
 os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES']=str(root.resolve())
 scene=sapien.Scene([sapien.physx.PhysxCpuSystem()]);scene.set_timestep(.004)
 pad=load_into_scene(scene,[0,0,.03,1,0,0,0],fixed_root=True,attach_visual=False,collision='sdf')
 art=pad.articulation
 native={j.name:{'K':j.stiffness,'D':j.damping,'effort':j.force_limit,'legacy':j.get_friction(),
                 'new':j.get_friction_params().tolist(),'limits':j.get_limits().tolist(),
                 'target':j.get_drive_target().tolist()} for j in art.get_active_joints()}
 comparisons=[]
 for name in ['common/xbox_one_s/motion/full_controls.json','robotwin/full_controls/mobility.urdf']:
  a=(root/name).read_bytes();b=(reference/name).read_bytes();comparisons.append({'file':name,'sha256':hashlib.sha256(a).hexdigest(),'byte_equal':a==b,'equals_tested_candidate':same_physics_input(name,a,b)})
 for _ in range(250):scene.step()
 cap=next(l for l in art.get_links() if l.name=='right_stick')
 for _ in range(250):cap.add_force_at_point([0,0,-12],cap.entity_pose.p);scene.step()
 state=pad.gamepad_state();positions=pad.joint_positions();controller=load_motion_contract('full_controls').signal_controller
 decoded=controller.decode_joint_targets(state)
 available=[n for n in CHANNEL_NAMES if state.is_available(n)]
 restored=GamepadState.from_mapping({n:state.channel(n) for n in available},device_id=state.device_id,available_channels=available)
 error=abs(decoded['right_stick_click']-positions['right_stick_click'])
 for _ in range(250):scene.step()
 released=pad.gamepad_state().channel('right_stick')
 result={'resources':str(root.resolve()),'SDF_public_loader_without_patch':True,
         'native_joints':native,'native_iterations':[art.get_solver_position_iterations(),art.get_solver_velocity_iterations()],
         'native_qf':art.get_qf().tolist(),'native_cone_mapping':pad._shaft_limit_mapping,
         'comparisons':comparisons,'mass_kg':sum(l.mass for l in art.get_links()),
         'signal_roundtrip':{'method':'Physical12N load, encode joint state, decode through original motion controller and serialize GamepadState. No q/qvel or drive-target writes.',
                             'loaded_public_signal':state.channel('right_stick'),'loaded_raw_fraction':positions['right_stick_click']/.0004,
                             'decoded_q_m':decoded['right_stick_click'],'actual_q_m':positions['right_stick_click'],
                             'decode_error_m':error,'serialized_values_equal':state.values==restored.values,'released_signal':released},
         'dag_stamps':[p.name for p in (root/'.stamps').glob('*.json')],
         'selected_calibration_sha256':hashlib.sha256((root/'.selected-calibration.json').read_bytes()).hexdigest()}
 result['passed']=all(x['equals_tested_candidate'] for x in comparisons) and len(native)==20 and state.channel('right_stick')>=.95 and error<=1e-7 and released<=.05 and state.values==restored.values
 output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'roundtrip':result['signal_roundtrip']}));return result['passed']
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();raise SystemExit(not run(a.resources,a.reference,a.output))
