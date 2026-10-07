import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {loadRig} from '../viewer/rig.mjs';
import {RIGID_VISUAL_GROUPS} from '../viewer/assembly_constraints.mjs';
const draft=JSON.parse(readFileSync(new URL('../viewer/xbox_one_s_draft.json',import.meta.url)));
const meshes=new Set(JSON.parse(readFileSync(new URL('../results/legacy_casper_1914_width_scaled_1708_proxy/inventory.json',import.meta.url))).objects.map(o=>o.name));
test('actual 1708 draft retains 21 null entries and activates no motion',()=>{
  const before=JSON.stringify(draft),loaded=loadRig(draft,meshes,RIGID_VISUAL_GROUPS);
  assert.equal(loaded.joints.length,0);assert.equal(loaded.pending.length,21);
  assert.equal(JSON.stringify(draft),before);
});
test('a complete fixture and unrelated pending entries can coexist',()=>{
  const j={channel:4,type:'prismatic',meshes:['A-Button'],axis:[0,1,0],pivot:[0,0,0],q0:0,q1:.003,evidence:'Synthetic fixture only'};
  const d={...draft,joints:[j],pending:draft.pending.filter(p=>p.channel!==4)};
  const loaded=loadRig(d,meshes,RIGID_VISUAL_GROUPS);
  assert.deepEqual(loaded.joints,[j]);assert.equal(loaded.pending.length,20);
});
test('pending fields cannot be omitted, defaulted or duplicated',()=>{
  for(const change of [{q0:0},{q0:undefined},{reason:''},{channel:21}])
    assert.throws(()=>loadRig({...draft,pending:[{...draft.pending[0],...change}]},meshes));
  assert.throws(()=>loadRig({...draft,pending:[draft.pending[0],draft.pending[0]]},meshes));
});
test('legacy schema 1 active rigs remain supported',()=>{
  assert.deepEqual(loadRig({schema:1,joints:[]},meshes),{joints:[],pending:[]});
});
