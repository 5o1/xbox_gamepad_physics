import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CHANNEL_NAMES,
  LAYOUT_ID,
  canonicalFrameToOverlayState,
  validateCanonicalFrame,
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
