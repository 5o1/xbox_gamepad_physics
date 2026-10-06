// Pure shared signal/joint coordinate mapping. No inferred physical constants.
import {validateState} from './gamepad_state.mjs';
export function validateRig(data, meshNames, rigidGroups = []) {
  if (data?.schema !== 1 || !Array.isArray(data.joints)) throw Error('Expected schema 1 and joints array');
  const used = new Set();
  for (const j of data.joints) {
    if (!Number.isInteger(j.channel) || j.channel < 0 || j.channel >= 21 || used.has(j.channel)) throw Error('Invalid/duplicate channel');
    used.add(j.channel);
    if (!['revolute', 'prismatic'].includes(j.type)) throw Error('Unknown joint type');
    if (!Array.isArray(j.meshes) || !j.meshes.length || j.meshes.some(n => !meshNames.has(n))) throw Error('Unknown mesh');
    for (const key of ['axis', 'pivot']) if (!Array.isArray(j[key]) || j[key].length !== 3 || !j[key].every(Number.isFinite)) throw Error(`Invalid ${key}`);
    if (Math.abs(Math.hypot(...j.axis) - 1) > 1e-8) throw Error('Axis must be unit length');
    if (![j.q0, j.q1].every(Number.isFinite) || j.q1 <= j.q0) throw Error('Invalid range');
    if (j.channel < 4 && (j.q0 >= 0 || j.q1 <= 0)) throw Error('Stick coordinates must bracket zero');
    if (typeof j.evidence !== 'string' || !j.evidence.trim()) throw Error('Missing provenance');
  }
  for (const group of rigidGroups) {
    if (!group.meshes.every(n => meshNames.has(n))) throw Error(`Incomplete visual assembly: ${group.id}`);
    // Every transform must affect either all or none of the rigid group.
    // This permits compound motion without inventing a hinge or switch model.
    for (const j of data.joints) {
      const count = group.meshes.filter(n => j.meshes.includes(n)).length;
      if (count !== 0 && count !== group.meshes.length)
        throw Error(`Joint ${j.channel} splits rigid visual assembly: ${group.id}`);
    }
  }
  return data.joints;
}

// Draft entries are explicitly inactive. null means unknown, never zero.
export function loadRig(data, meshNames, rigidGroups = []) {
  const joints = validateRig(data, meshNames, rigidGroups);
  const pending = data.pending ?? [];
  if (!Array.isArray(pending)) throw Error('Invalid pending entries');
  const used = new Set(joints.map(j => j.channel));
  for (const entry of pending) {
    if (!Number.isInteger(entry.channel) || entry.channel < 0 || entry.channel >= 21 || used.has(entry.channel))
      throw Error('Invalid/duplicate pending channel');
    used.add(entry.channel);
    if (typeof entry.reason !== 'string' || !entry.reason.trim()) throw Error('Missing pending reason');
    // Draft details belong in the evidence/specification, not in a silently
    // half-enabled motion model. Promotion requires a complete active joint.
    for (const key of ['type','meshes','axis','pivot','q0','q1'])
      if (entry[key] !== null) throw Error(`Pending ${key} must be explicitly null`);
  }
  return {joints, pending};
}
export function toJoint(j, value) {
  if (!Number.isFinite(value) || value < (j.channel < 4 ? -1 : 0) || value > 1) throw Error('Invalid signal');
  return j.channel < 4 ? (value < 0 ? -value * j.q0 : value * j.q1) : j.q0 + value * (j.q1 - j.q0);
}
export function toSignal(j, q) {
  if (!Number.isFinite(q)) throw Error('Invalid coordinate');
  const value = j.channel < 4 ? (q < 0 ? -q / j.q0 : q / j.q1) : (q - j.q0) / (j.q1 - j.q0);
  return Math.max(j.channel < 4 ? -1 : 0, Math.min(1, value));
}
export function jointCoordinates(joints, state) {
  validateState(state);
  return joints.map(j => toJoint(j, state[j.channel]));
}

// Schema 1 composes world-frame transforms in list order. Later transforms
// carry an earlier joint's axis and pivot into its displayed world frame.
// Rodrigues' formula; no Xbox dimensions or mechanical assumptions here.
export function carriedJointFrame(joints, joint, mesh, state) {
  const index = joints.indexOf(joint);
  if (index < 0 || !joint.meshes.includes(mesh)) throw Error('Joint does not affect mesh');
  validateState(state);
  let axis = [...joint.axis], pivot = [...joint.pivot];
  const dot = (a,b) => a.reduce((s,x,i)=>s+x*b[i],0);
  const rotate = (v,a,q) => {
    const c=Math.cos(q),s=Math.sin(q),d=dot(a,v);
    const cross=[a[1]*v[2]-a[2]*v[1],a[2]*v[0]-a[0]*v[2],a[0]*v[1]-a[1]*v[0]];
    return v.map((x,i)=>x*c+cross[i]*s+a[i]*d*(1-c));
  };
  for (const next of joints.slice(index+1).filter(j=>j.meshes.includes(mesh))) {
    const q=toJoint(next,state[next.channel])-toJoint(next,0);
    if(next.type==='prismatic') pivot=pivot.map((x,i)=>x+next.axis[i]*q);
    else {
      pivot=rotate(pivot.map((x,i)=>x-next.pivot[i]),next.axis,q).map((x,i)=>x+next.pivot[i]);
      axis=rotate(axis,next.axis,q);
    }
  }
  return {axis,pivot};
}
