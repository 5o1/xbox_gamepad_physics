// Target topology requirement, not certification of candidate mesh dimensions.
// Source and inspected photograph: sources/1708_dpad_assembly.json.
export const RIGID_VISUAL_GROUPS = [{
  id: 'dpad_cap',
  meshes: ['DPadDown', 'DPadLeft', 'DPadRight', 'DPadUp'],
  evidence: 'iFixit 1708 guide 98147 step 7: removable cross-shaped cap; four source visual objects must not be animated as independent plungers',
}];
