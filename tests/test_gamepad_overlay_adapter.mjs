import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CHANNEL_NAMES,
  LAYOUT_ID,
  canonicalFrameToOverlayState,
  validateCanonicalFrame,
  installCanonicalSource,
} from '../viewer/gamepad_overlay/canonical_adapter.mjs';


function frame() {
  return {
    layout_id: LAYOUT_ID,
    values: new Array(32).fill(0),
    available_mask: new Array(32).fill(true),
    task_mask: new Array(32).fill(true),
    device_id: 1,
  };
}

test('canonical 32-channel state maps by semantic name into upstream overlay state', () => {
  const input = frame();
  const set = (name, value) => { input.values[CHANNEL_NAMES.indexOf(name)] = value; };
  set('left_x', 0.6);
  set('left_y', -0.8);
  set('left_trigger', 0.4);
  set('south', 1);
  set('dpad_left', 1);
  const output = canonicalFrameToOverlayState(input);
  assert.equal(output.LX, 0.6);
  assert.equal(output.LY, -0.8);
  assert.equal(output.LT, 0.4);
  assert.equal(output.A, 1);
  assert.equal(output.DX, -1);
});

test('zero cannot hide an invalid availability/task relation', () => {
  const input = frame();
  input.available_mask[0] = false;
  assert.throws(() => validateCanonicalFrame(input), /Task channel left_x is unavailable/);
  input.task_mask[0] = false;
  input.values[0] = 0.25;
  assert.throws(() => validateCanonicalFrame(input), /Unavailable channel left_x must be zero/);
});

test('canonical adapter preserves continuous button and dpad values', () => {
  const input = frame();
  const set = (name, value) => { input.values[CHANNEL_NAMES.indexOf(name)] = value; };
  set('dpad_up', 5.4e-7);
  set('dpad_right', 4.4e-6);
  set('south', 0.37);
  const output = canonicalFrameToOverlayState(input);
  assert.equal(output.DX, 4.4e-6);
  assert.equal(output.DY, -5.4e-7);
  assert.equal(output.A, 0.37);
});

test('canonical source delivers only validated 32-channel frames to its sink', async () => {
  const saved={window:globalThis.window,document:globalThis.document,raf:globalThis.requestAnimationFrame,location:globalThis.location};
  const states=[];let fallbackCalls=0;
  globalThis.window={location:{search:'?source=canonical'},OverlayInput:{
    createGamepadSource(){fallbackCalls++;throw new Error('browser/demo source must not be used');},
  }};
  globalThis.location=window.location;
  const glow={left:false,right:false};
  globalThis.document={getElementById(){return null;},querySelectorAll(selector){
    const side=selector.includes('data-side="right"')?'right':'left';
    return [{classList:{toggle(name,active){assert.equal(name,'signal-active');glow[side]=active;}}}];
  }};
  globalThis.requestAnimationFrame=callback=>setImmediate(callback);
  try {
    const adapter=installCanonicalSource();
    window.OverlayInput.createGamepadSource({mode:'browser',onState:value=>states.push(value)}).start();
    adapter.markReady();
    const input=frame();input.values[CHANNEL_NAMES.indexOf('guide')]=.37;
    input.values[CHANNEL_NAMES.indexOf('left_x')]=.6;
    const mapped=await adapter.applyFrame(input);
    assert.deepEqual(states,[mapped]);assert.equal(mapped.GUIDE,.37);assert.equal(mapped.LX,.6);
    assert.equal(fallbackCalls,0);
    assert.deepEqual(glow,{left:true,right:false});
    await assert.rejects(adapter.applyFrame({A:1,DY:1}),/layout_id/);
    await assert.rejects(adapter.applyFrame({...input,values:input.values.slice(0,31)}),/32 gamepad values/);
    assert.equal(states.length,1,'invalid or non-canonical input cannot reach the renderer');
    const right=frame();right.values[CHANNEL_NAMES.indexOf('right_y')]=-.7;
    await adapter.applyFrame(right);
    assert.deepEqual(glow,{left:false,right:true});
    await adapter.applyFrame(frame());
    assert.deepEqual(glow,{left:false,right:false});
  } finally {
    globalThis.window=saved.window;globalThis.document=saved.document;globalThis.requestAnimationFrame=saved.raf;globalThis.location=saved.location;
  }
});
