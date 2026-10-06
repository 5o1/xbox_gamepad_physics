"""Read original FBX rig geometry; never promote artist transforms to physics."""
import bpy
import json
import sys
from pathlib import Path
from mathutils import Vector

source, destination = map(Path, sys.argv[sys.argv.index('--') + 1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(source))
scene = bpy.context.scene
scene.frame_set(1)
matrix = lambda m: [list(row) for row in m]
parts = []
for obj in scene.objects:
    if obj.type != 'MESH':
        continue
    weights = {}
    for vertex in obj.data.vertices:
        for group in vertex.groups:
            name = obj.vertex_groups[group.group].name
            item = weights.setdefault(name, {'vertices': 0, 'min_weight': 1.0, 'max_weight': 0.0})
            item['vertices'] += 1
            item['min_weight'] = min(item['min_weight'], group.weight)
            item['max_weight'] = max(item['max_weight'], group.weight)
    parts.append({
        'name': obj.name, 'parent': obj.parent.name if obj.parent else None,
        'parent_type': obj.parent_type, 'parent_bone': obj.parent_bone,
        'matrix_world_at_frame_1_native': matrix(obj.matrix_world),
        'mesh_local_bounds_native': [list(v) for v in obj.bound_box],
        'vertex_groups': weights,
        'modifiers': [{'type': m.type, 'object': m.object.name if getattr(m, 'object', None) else None} for m in obj.modifiers],
        'physical_joint_axis': None, 'physical_joint_origin_m': None,
        'physical_limits': None, 'mass_kg': None,
        'unknown_reason': 'Artist asset has no verified mechanical calibration.'
    })
rigs = []
for obj in scene.objects:
    if obj.type == 'ARMATURE':
        rigs.append({'name': obj.name, 'matrix_world': matrix(obj.matrix_world),
            'bones': [{'name': b.name, 'parent': b.parent.name if b.parent else None,
                       'head_local_native': list(b.head_local), 'tail_local_native': list(b.tail_local),
                       'matrix_local': matrix(b.matrix_local)} for b in obj.data.bones]})
report = {'source': str(source), 'evidence': 'Direct Blender FBX import; mesh weights and rest bones read without editing source',
          'scene_unit_settings': {'system': scene.unit_settings.system, 'scale_length': scene.unit_settings.scale_length},
          'physical_scale_verified': False, 'parts': parts, 'artist_rigs_not_physics': rigs}
assert len(parts) == 16, 'Unexpected source mesh count; stop instead of accepting a different asset'
assert len({p['name'] for p in parts}) == 16
destination.write_text(json.dumps(report, indent=2))
print('AUDIT_OK: 16 mesh parts; physical parameters remain null')
