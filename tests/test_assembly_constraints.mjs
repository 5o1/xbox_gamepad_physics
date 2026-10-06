import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateRig} from '../viewer/rig.mjs';
import {RIGID_VISUAL_GROUPS} from '../viewer/assembly_constraints.mjs';
const group=RIGID_VISUAL_GROUPS[0];
const names=new Set(JSON.parse(readFileSync(new URL('../results/width_proxy_1708/inventory.json',import.meta.url))).objects.map(x=>x.name));
const joint=meshes=>({channel:16,type:'revolute',axis:[1,0,0],pivot:[0,0,0],q0:0,q1:.1,meshes,evidence:'Synthetic constraint test, not Xbox motion'});
test('actual candidate inventory contains complete dpad visual group',()=>{
  assert.ok(group.meshes.every(n=>names.has(n)));
  validateRig({schema:1,joints:[]},names,RIGID_VISUAL_GROUPS);
});
test('independent direction animation is rejected',()=>{
  for(const name of group.meshes)
    assert.throws(()=>validateRig({schema:1,joints:[joint([name])]},names,RIGID_VISUAL_GROUPS),/splits rigid/);
});
test('compound transformations can move the whole cap together',()=>{
  const a=joint([...group.meshes]),b={...a,channel:18,axis:[0,1,0]};
  assert.equal(validateRig({schema:1,joints:[a,b]},names,RIGID_VISUAL_GROUPS).length,2);
  assert.throws(()=>validateRig({schema:1,joints:[a,{...b,meshes:group.meshes.slice(1)}]},names,RIGID_VISUAL_GROUPS),/splits rigid/);
});
test('missing group mesh is not silently accepted',()=>{
  const missing=new Set(names);missing.delete(group.meshes[0]);
  assert.throws(()=>validateRig({schema:1,joints:[]},missing,RIGID_VISUAL_GROUPS),/Incomplete visual assembly/);
});
