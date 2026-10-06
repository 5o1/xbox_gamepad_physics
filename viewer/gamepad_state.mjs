// W3C standard layout: https://www.w3.org/TR/2025/WD-gamepad-20250710/#remapping
// Concatenating axes and button values is our transport format, not a W3C tensor standard.
export const AXES = Object.freeze(['LX', 'LY', 'RX', 'RY']);
export const BUTTONS = Object.freeze([
  'A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'View', 'Menu',
  'L3', 'R3', 'DUp', 'DDown', 'DLeft', 'DRight', 'Guide',
]);

export function neutralState() {
  return new Float32Array(21);
}

export function validateState(state) {
  if (!state || state.length !== 21) throw new Error('Expected 21 channel values');
  for (let i = 0; i < state.length; i++) {
    const low = i < 4 ? -1 : 0;
    if (!Number.isFinite(state[i]) || state[i] < low || state[i] > 1) {
      throw new Error(`Channel ${i} outside [${low}, 1]`);
    }
  }
  return state;
}

export function readStandardGamepad(pad, receivedAt) {
  if (!Number.isFinite(receivedAt)) throw new Error('Missing finite receipt time');
  // Browser-reported data, not USB HID packets. Snapshot before layout validation
  // so an unsupported layout is inspectable without being used as control input.
  const raw = pad?.connected ? {
    axes: Array.from(pad.axes ?? []),
    buttons: Array.from(pad.buttons ?? [], b => ({value:b?.value, pressed:b?.pressed, touched:b?.touched})),
  } : null;
  const metadata = {receivedAt, deviceTimestamp: Number.isFinite(pad?.timestamp) ? pad.timestamp : null,
    id:pad?.id??null, index:pad?.index??null, mapping:pad?.mapping??null, raw};
  const invalid = reason => ({
    valid: false, reason, values: neutralState(), available: new Array(21).fill(false),
    ...metadata,
  });
  if (!pad?.connected) return invalid('disconnected');
  if (pad.mapping !== 'standard') return invalid('unrecognized_mapping');
  // Guide may be unavailable due to browser/OS interception; never pretend it was read.
  if (pad.axes?.length < 4 || pad.buttons?.length < 16 || !pad.axes || !pad.buttons) {
    return invalid('missing_required_channels');
  }
  const mapped = [...raw.axes.slice(0, 4), ...raw.buttons.slice(0, 17).map(button => button.value)];
  const available = Array.from({length: 21}, (_, i) => i < mapped.length);
  while (mapped.length < 21) mapped.push(0);
  try { validateState(mapped); } catch { return invalid('invalid_channel_value'); }
  return {
    valid: true, reason: null, values: Float32Array.from(mapped), available, ...metadata,
  };
}

export class InputSession {
  constructor() { this.mode = 'mouse'; this.frame = this.empty('initial'); }
  empty(reason) { return {valid: false, reason, values: neutralState(), available: new Array(21).fill(false)}; }
  setMode(mode) {
    if (!['mouse', 'device'].includes(mode)) throw new Error('Unknown input mode');
    this.mode = mode;
    this.clear('mode_change');
  }
  clear(reason) { this.frame = this.empty(reason); }
  updateDevice(pad, receivedAt) {
    if (this.mode !== 'device') throw new Error('Device cannot overwrite mouse mode');
    this.frame = readStandardGamepad(pad, receivedAt);
    return this.frame;
  }
  updateFromPartPose(values, receivedAt) {
    if (this.mode !== 'mouse') throw new Error('Mouse cannot overwrite device mode');
    validateState(values);
    if (!Number.isFinite(receivedAt)) throw new Error('Missing finite receipt time');
    this.frame = {valid: true, values: Float32Array.from(values),
      available: new Array(21).fill(true), receivedAt, source: 'part_pose'};
    return this.frame;
  }
}
