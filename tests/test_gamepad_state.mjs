import test from 'node:test';
import assert from 'node:assert/strict';
import {InputSession, readStandardGamepad, neutralState, validateState} from '../viewer/gamepad_state.mjs';

const pad = () => ({connected: true, mapping: 'standard', id: 'synthetic standard pad',
  index: 0, timestamp: 10, axes: [-.5, .25, .75, -.125],
  buttons: Array.from({length: 17}, () => ({value: 0, pressed: false}))});

test('standard layout preserves axes, trigger analog values, and concurrent buttons', () => {
  const p = pad(); p.buttons[0].value = 1; p.buttons[6].value = .375; p.buttons[7].value = .625;
  const result = readStandardGamepad(p, 12);
  assert.equal(result.valid, true);
  assert.deepEqual(Array.from(result.values.slice(0, 4)), p.axes);
  assert.equal(result.values[4], 1);
  assert.equal(result.values[10], .375); assert.equal(result.values[11], .625);
  assert.equal(result.deviceTimestamp, 10); assert.equal(result.receivedAt, 12);
});
test('missing Guide is marked unavailable, not claimed as a measured zero', () => {
  const p = pad(); p.buttons.pop(); const result = readStandardGamepad(p, 12);
  assert.equal(result.valid, true); assert.equal(result.available[20], false);
});
test('unknown mapping and malformed data fail explicitly', () => {
  const p = pad(); p.mapping = ''; assert.equal(readStandardGamepad(p, 12).valid, false);
  p.mapping = 'standard'; p.axes[0] = NaN; assert.equal(readStandardGamepad(p, 12).valid, false);
  p.axes[0] = 1.01; assert.equal(readStandardGamepad(p, 12).valid, false);
  assert.throws(() => validateState([0]));
});
test('disconnect and explicit lifecycle reset clear stale values', () => {
  const session = new InputSession(); session.setMode('device'); session.updateDevice(pad(), 12);
  assert.equal(session.updateDevice(null, 13).valid, false);
  assert.deepEqual(session.frame.values, neutralState());
  session.updateDevice(pad(), 14); session.clear('focus_loss');
  assert.equal(session.frame.valid, false); assert.deepEqual(session.frame.values, neutralState());
});
test('mode switch clears input and prevents competing sources', () => {
  const session = new InputSession(); const values = neutralState(); values[0] = .5;
  const available=new Array(21).fill(false);available[0]=true;
  session.updateFromPartPose(values, 1, available); values[0] = 0;
  assert.equal(session.frame.values[0], .5);
  assert.equal(session.frame.available[0],true);assert.equal(session.frame.available[1],false);
  session.setMode('device'); assert.equal(session.frame.valid, false);
  assert.throws(() => session.updateFromPartPose(values, 2, available));
  session.setMode('mouse'); assert.throws(() => session.updateDevice(pad(), 3));
});
test('mouse partial rig marks only configured channels available',()=>{
  const session=new InputSession(),values=neutralState(),available=new Array(21).fill(false);
  values[4]=.75;values[5]=.5;available[4]=true;
  const frame=session.updateFromPartPose(values,3,available);
  assert.equal(frame.valid,true);assert.equal(frame.values[4],.75);assert.equal(frame.values[5],0);
  assert.deepEqual(frame.available,available);
  assert.throws(()=>session.updateFromPartPose(values,4,new Array(20).fill(false)),/availability mask/);
});
