import test from 'node:test';
import assert from 'node:assert/strict';
import {validateRig,toJoint,toSignal,carriedJointFrame} from '../viewer/rig.mjs';
const joint=()=>({channel:0,type:'revolute',axis:[1,0,0],pivot:[0,0,0],q0:-.2,q1:.3,meshes:['fixture'],evidence:'Synthetic test only'});
test('asymmetric axis range roundtrips through neutral and endpoints',()=>{
  const j=joint();validateRig({schema:1,joints:[j]},new Set(['fixture']));
  for(const v of [-1,-.5,0,.5,1])assert.ok(Math.abs(toSignal(j,toJoint(j,v))-v)<1e-12);
});
test('analog button and nonzero rest coordinate roundtrip',()=>{
  const j={...joint(),channel:10,q0:.1,q1:.5};
  for(const v of [0,.25,.75,1])assert.ok(Math.abs(toSignal(j,toJoint(j,v))-v)<1e-12);
});
test('unknown geometry, missing evidence and non-unit axis rejected',()=>{
  for(const changed of [{meshes:['absent']},{evidence:''},{axis:[2,0,0]},{q1:null}])
    assert.throws(()=>validateRig({schema:1,joints:[{...joint(),...changed}]},new Set(['fixture'])));
});
test('earlier axis follows later rotation and translation, not unrelated meshes',()=>{
  const a=joint();
  const b={...joint(),channel:1,axis:[0,0,1],pivot:[1,0,0],q1:Math.PI/2};
  const c={...joint(),channel:4,type:'prismatic',axis:[0,1,0],q0:0,q1:2};
  const other={...c,channel:5,meshes:['other']};
  const state=Array(21).fill(0);state[1]=1;state[4]=1;state[5]=1;
  const f=carriedJointFrame([a,b,c,other],a,'fixture',state);
  const close=(actual,expected)=>actual.forEach((v,i)=>assert.ok(Math.abs(v-expected[i])<1e-12));
  close(f.axis,[0,1,0]);close(f.pivot,[1,1,0]);
  close(carriedJointFrame([a,b,c],c,'fixture',state).axis,[0,1,0]);
});
test('neutral composition preserves axis and pivot; invalid membership rejected',()=>{
  const a=joint(),b={...joint(),channel:1,axis:[0,1,0]};
  const state=Array(21).fill(0);
  assert.deepEqual(carriedJointFrame([a,b],a,'fixture',state),{axis:a.axis,pivot:a.pivot});
  assert.throws(()=>carriedJointFrame([a],a,'absent',state));
});
