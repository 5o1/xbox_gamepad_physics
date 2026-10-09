import test from 'node:test';
import assert from 'node:assert/strict';
import {toCoordinate,toSignal} from '../scripts/coordinate_mapping.mjs';

test('synthetic axis mapping roundtrips neutral and endpoints',()=>{
  for(const value of [-1,-.5,0,.5,1]){
    const coordinate=toCoordinate(0,-.2,.3,value);
    assert.ok(Math.abs(toSignal(0,-.2,.3,coordinate)-value)<1e-12);
  }
});

test('synthetic analog-button mapping roundtrips and validates input',()=>{
  for(const value of [0,.25,.75,1]){
    const coordinate=toCoordinate(10,.1,.5,value);
    assert.ok(Math.abs(toSignal(10,.1,.5,coordinate)-value)<1e-12);
  }
  assert.throws(()=>toCoordinate(0,0,.3,.5),/Invalid/);
  assert.throws(()=>toCoordinate(21,0,.3,.5),/Invalid/);
});
