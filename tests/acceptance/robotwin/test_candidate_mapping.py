"""RoboTwin dimensional-friction parsing and native application boundaries."""
import copy,json,math,os,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xbox_gamepad_physics.backends.common.model import Parameter,Evidence
from xbox_gamepad_physics.robotwin.physical import joint_friction_params,require_robotwin_dynamics,solver_iterations,viscous_mapping

def value(x,unit):
 return Parameter(x,unit,(Evidence('test fixture','explicit input','Adapter test only','Fixed test value',category='fixture_definition'),)).as_dict()
def record(s=.00003,d=.00001,v=.0001):
 return dict(static_effort=value(s,'N*m'),dynamic_effort=value(d,'N*m'),viscous=value(v,'N*m*s/rad'))
class InputTest(unittest.TestCase):
 def test_legacy_absence_and_dimensional_values(self):
  self.assertEqual(joint_friction_params({},{}),{})
  self.assertEqual(joint_friction_params({'tilt':record()},{'tilt':'rad'})['tilt'],(.00003,.00001,.0001))
 def test_missing_unknown_units_null_and_order_rejected(self):
  cases=[];r=record();del r['viscous'];cases.append({'tilt':r})
  r=record();r['static_effort']=value(.1,'N');cases.append({'tilt':r})
  r=record();r['viscous']={'value':None,'unit':'N*m*s/rad','evidence':[],'missing_reason':'unknown'};cases.append({'tilt':r})
  cases.extend([{'tilt':record(.00001,.00003)}, {'unknown':record()}])
  for x in cases:
   with self.subTest(x=x),self.assertRaises(ValueError):joint_friction_params(x,{'tilt':'rad'})
 def test_linear_units_and_nonfinite_inputs(self):
  r=dict(static_effort=value(1,'N'),dynamic_effort=value(.5,'N'),viscous=value(.2,'N*s/m'))
  self.assertEqual(joint_friction_params({'slide':r},{'slide':'m'})['slide'],(1,.5,.2))
  for bad in [-1,float('nan'),float('inf'),True]:
   r=record();r['viscous']['value']=bad
   with self.assertRaises(ValueError):joint_friction_params({'tilt':r},{'tilt':'rad'})
 def test_new_mode_clears_legacy_without_touching_other_joint(self):
  base={'stiffness':1.,'drive_damping':1.,'passive_damping':0.,'effort':1.,'target':0.,'unit':'rad','friction':.1}
  rows={'tilt':dict(base),'other':dict(base)};cal=SimpleNamespace(backend_options={'robotwin':{'joint_friction_params':{'tilt':record()}}})
  require_robotwin_dynamics(rows,cal);self.assertEqual(rows['tilt']['friction'],0);self.assertEqual(rows['other']['friction'],.1)
 def test_explicit_solver_policy_and_channel_validation(self):
  self.assertIsNone(solver_iterations({}))
  policy={'solver_iterations':{'position':value(64,'1'),'velocity':value(16,'1')}}
  self.assertEqual(solver_iterations(policy),(64,16))
  for invalid in [None,{}, {'position':value(64,'1')}, {'position':value(64.,'1'),'velocity':value(16,'1')}, {'position':value(64,'rad'),'velocity':value(16,'1')}]:
   with self.subTest(invalid=invalid),self.assertRaises(ValueError):solver_iterations({'solver_iterations':invalid})
  self.assertEqual(viscous_mapping({}),'native_friction')
  self.assertEqual(viscous_mapping({'joint_friction_viscous_mapping':'drive_damping'}),'drive_damping')
  with self.assertRaises(ValueError):viscous_mapping({'joint_friction_viscous_mapping':None})
class NativeTest(unittest.TestCase):
 def test_native_implicit_viscous_mapping_is_not_double_counted(self):
  resources=os.environ.get('CANDIDATE_TEST_RESOURCES')
  if not resources:self.skipTest('requires private resource copy')
  import sapien
  from xbox_gamepad_physics.robotwin import load_into_scene
  root=Path(resources);manifest=root/'robotwin/full_controls/manifest.json';original=manifest.read_bytes()
  try:
   raw=json.loads(original);base=next(j['damping'] for j in raw['joint_dynamics'] if j['name']=='left_stick_x')
   raw['backend_options']['robotwin'].update(joint_friction_params={'left_stick_x':record()},joint_friction_viscous_mapping='drive_damping')
   manifest.write_text(json.dumps(raw)+'\n');scene=sapien.Scene([sapien.physx.PhysxCpuSystem()])
   with patch('xbox_gamepad_physics.resources.resource_root',return_value=root):pad=load_into_scene(scene,[0,0,.03,1,0,0,0],fixed_root=True,attach_visual=False)
   j=next(j for j in pad.articulation.get_active_joints() if j.name=='left_stick_x')
   self.assertEqual(j.get_friction(),0);self.assertEqual(j.get_friction_params()[2],0)
   self.assertAlmostEqual(j.damping,base+.0001,places=9)
  finally:manifest.write_bytes(original)
 def test_a1_rejects_native_d6_even_with_same_setter_name(self):
  resources=os.environ.get('CANDIDATE_TEST_RESOURCES')
  if not resources:self.skipTest('requires private a1 resource copy')
  import sapien
  from importlib.metadata import version
  from xbox_gamepad_physics.robotwin import load_into_scene
  from xbox_gamepad_physics.robotwin.errors import SceneCompatibilityError
  if version('sapien')!='3.0.3+concon.physx5.6.1.a1':self.skipTest('specific incompatible a1 dependency check')
  root=Path(resources);manifest=root/'robotwin/full_controls/manifest.json';original=manifest.read_bytes()
  try:
   raw=json.loads(original);raw['backend_options']['robotwin']['shaft_tilt_limit']={'mechanism':'native_d6_cone'};manifest.write_text(json.dumps(raw)+'\n')
   scene=sapien.Scene([sapien.physx.PhysxCpuSystem()])
   with patch('xbox_gamepad_physics.resources.resource_root',return_value=root),self.assertRaisesRegex(SceneCompatibilityError,'requires sapien==.*a3'):
    load_into_scene(scene,[.1,.2,.3,1,0,0,0],fixed_root=True,attach_visual=False)
  finally:manifest.write_bytes(original)
 def test_native_new_and_legacy_resources(self):
  resources=os.environ.get('CANDIDATE_TEST_RESOURCES')
  if not resources:self.skipTest('requires private a1 resource copy')
  import sapien
  from xbox_gamepad_physics.robotwin import load_into_scene
  root=Path(resources);manifest=root/'robotwin/full_controls/manifest.json';original=manifest.read_bytes();results=[]
  try:
   for new in [False,True]:
    raw=json.loads(original)
    if new:raw.setdefault('backend_options',{}).setdefault('robotwin',{})['joint_friction_params']={'left_stick_x':record()}
    manifest.write_text(json.dumps(raw,indent=2)+'\n')
    scene=sapien.Scene([sapien.physx.PhysxCpuSystem()]);scene.set_timestep(.004)
    with patch('xbox_gamepad_physics.resources.resource_root',return_value=root):pad=load_into_scene(scene,[0,0,.03,1,0,0,0],fixed_root=True,attach_visual=False)
    j=next(j for j in pad.articulation.get_active_joints() if j.name=='left_stick_x')
    actual=j.get_friction_params().tolist();coef=j.get_friction()
    self.assertAlmostEqual(coef,0 if new else .1,places=7)
    for a,b in zip(actual,[.00003,.00001,.0001] if new else [0,0,0]):self.assertAlmostEqual(a,b,places=9)
    for _ in range(20):scene.step()
    results.append({'new':new,'legacy_coefficient':coef,'friction_params':actual,'dof':pad.articulation.dof,'qf':pad.articulation.get_qf().tolist(),'q':pad.joint_positions()})
   output=os.environ.get('CANDIDATE_TEST_OUTPUT')
   if output:Path(output).write_text(json.dumps(results,indent=2)+'\n')
  finally:manifest.write_bytes(original)
if __name__=='__main__':unittest.main()
