import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {configuredChannels,evaluateProfile,nodeSteps,sourceToGltfVector,stateWithJointCoordinate,validateProfile} from '../viewer/kinematics.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
execFileSync('python3',['scripts/build_kinematics.py','--write'],{cwd:root,stdio:'ignore'});
const profile=JSON.parse(await readFile(new URL('../build/generated/kinematics/xbox_one_s.json',import.meta.url)));
const evidence=JSON.parse(await readFile(new URL('../build/generated/kinematics/xbox_one_s_evidence.json',import.meta.url)));
const nodes=new Set(profile.nodes.map(node=>node.source_node));

test('profile validates with exact 21-channel coverage and fail-closed status',()=>{
  assert.equal(validateProfile(profile,evidence,nodes),profile);
  assert.deepEqual(configuredChannels(profile),new Array(21).fill(true));
  const promoted=structuredClone(profile);promoted.acceptance.physical_acceptance=true;
  assert.throws(()=>validateProfile(promoted,evidence,nodes),/physical_acceptance/);
});

test('semantic profile mutations fail closed',()=>{
  const mutations=[
    ['duplicate channel name',candidate=>{candidate.channels[1].name=candidate.channels[0].name;},/standard tensor contract/],
    ['driver range differs from channel',candidate=>{candidate.joints.find(joint=>joint.id==='left_stick_x').driver.signal_range=[0,1];},/range mismatch/],
    ['radial constraint mixes joint types and units',candidate=>{candidate.constraints[0].joint_ids=['left_stick_x','a_press'];},/type\/unit\/parameter mismatch/],
    ['physical event is not declared',candidate=>{candidate.joints.find(joint=>joint.id==='pair_press').driver.event='undeclared';},/physical event/],
    ['mapping pretends to provide a different differentiability contract',candidate=>{candidate.mapping_semantics.kind='piecewise_linear_differentiable_surrogate';},/forward-only/],
    ['axis differs from evidence',candidate=>{candidate.joints.find(joint=>joint.id==='left_stick_x').axis_source=[1,0,0];},/axis\/pivot differs/],
    ['pivot differs from evidence',candidate=>{candidate.joints.find(joint=>joint.id==='right_trigger_hinge').pivot_source_m[0]+=1e-6;},/axis\/pivot differs/],
    ['limits differ from evidence',candidate=>{candidate.joints.find(joint=>joint.id==='a_press').limits[1]*=.5;},/limits differ/],
  ];
  for(const [name,mutate,pattern] of mutations){
    const candidate=structuredClone(profile);mutate(candidate);
    assert.throws(()=>validateProfile(candidate,evidence,nodes),pattern,name);
  }
});

test('evidence IDs and physical-event declarations fail closed',()=>{
  const unresolved=structuredClone(evidence);unresolved.parameters.a_travel.evidence=['missing_source'];
  assert.throws(()=>validateProfile(profile,unresolved,nodes),/unresolved evidence ID/);
  const orphan=structuredClone(profile);orphan.physical_events.push({name:'orphan',joint_id:'a_press',tensor_channel:null});
  assert.throws(()=>validateProfile(orphan,evidence,nodes),/bijection/);
});

test('neutral and simultaneous inputs produce finite coordinates',()=>{
  const state=new Float32Array(21);state[0]=.6;state[1]=-.8;state[4]=1;state[10]=.4;state[11]=.7;
  const result=evaluateProfile(profile,state);
  assert.equal(result.projections.length,0);
  assert.ok(Object.values(result.coordinates).every(Number.isFinite));
  assert.ok(Math.abs(result.represented[0]-.6)<1e-6);
  assert.ok(Math.abs(result.represented[1]+.8)<1e-6);
  assert.equal(result.represented[4],1);
});

test('stick and dpad envelopes expose rather than hide projection loss',()=>{
  const state=new Float32Array(21);state[0]=1;state[1]=1;state[16]=1;state[19]=1;
  const result=evaluateProfile(profile,state);
  assert.deepEqual(result.projections.map(item=>item.constraint),['left_stick_radial_envelope','dpad_radial_envelope']);
  assert.ok(Math.abs(result.represented[0]-Math.SQRT1_2)<1e-6);
  assert.ok(Math.abs(result.represented[1]-Math.SQRT1_2)<1e-6);
  assert.ok(Math.abs(result.represented[16]-Math.SQRT1_2)<1e-6);
  assert.ok(Math.abs(result.represented[19]-Math.SQRT1_2)<1e-6);
});

test('pair remains outside the 21-value tensor',()=>{
  const result=evaluateProfile(profile,new Float32Array(21),{pair_bind_connect:1});
  assert.equal(result.represented.length,21);
  assert.equal(result.representedEvents.pair_bind_connect,1);
  assert.ok(result.coordinates.pair_press>0);
  assert.throws(()=>stateWithJointCoordinate(profile,new Float32Array(21),'pair_press',1),/not a tensor/);
});

test('source-to-gltf conversion and ordered node steps are explicit',()=>{
  assert.deepEqual(sourceToGltfVector([1,2,3]),[1,3,-2]);
  const result=evaluateProfile(profile,new Float32Array(21));
  const left=profile.nodes.find(node=>node.control==='left_stick');
  const steps=nodeSteps(profile,left.source_node,result);
  assert.deepEqual(steps.map(step=>step.id),['left_stick_x','left_stick_y','left_stick_click']);
  assert.deepEqual(steps.map(step=>step.type),['revolute','revolute','prismatic']);
});

test('joint-coordinate editing uses the same signal path',()=>{
  const joint=profile.joints.find(item=>item.id==='a_press');
  const state=stateWithJointCoordinate(profile,new Float32Array(21),joint.id,joint.limits[1]/2);
  assert.ok(Math.abs(state[4]-.5)<1e-6);
  const result=evaluateProfile(profile,state);
  assert.ok(Math.abs(result.coordinates[joint.id]-joint.limits[1]/2)<1e-10);
});
