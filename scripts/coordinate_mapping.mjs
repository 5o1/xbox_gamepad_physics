// Standalone synthetic signal/coordinate mapping used for Torch parity tests.
// This is not the browser viewer runtime and carries no Xbox mechanics.
export function toCoordinate(channel, q0, q1, value) {
  const lower = channel < 4 ? -1 : 0;
  if (!Number.isInteger(channel) || channel < 0 || channel >= 21 ||
      ![q0, q1, value].every(Number.isFinite) || q0 >= q1 ||
      value < lower || value > 1 || (channel < 4 && !(q0 < 0 && q1 > 0))) {
    throw Error('Invalid coordinate mapping input');
  }
  return channel < 4
    ? (value < 0 ? -value * q0 : value * q1)
    : q0 + value * (q1 - q0);
}

export function toSignal(channel, q0, q1, coordinate) {
  if (!Number.isInteger(channel) || channel < 0 || channel >= 21 ||
      ![q0, q1, coordinate].every(Number.isFinite) || q0 >= q1 ||
      (channel < 4 && !(q0 < 0 && q1 > 0))) {
    throw Error('Invalid coordinate mapping input');
  }
  const value = channel < 4
    ? (coordinate < 0 ? -coordinate / q0 : coordinate / q1)
    : (coordinate - q0) / (q1 - q0);
  return Math.max(channel < 4 ? -1 : 0, Math.min(1, value));
}
