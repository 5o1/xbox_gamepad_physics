"""Bake the identified BatonyRobson GLB into static visual parts, not physics.

Harness: pinned source hash, exact mesh count, finite geometry, per-part hashes,
and a manifest retaining original evaluated transforms and source materials.
All unverified metric or mechanical quantities remain null.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_RECORD = PROJECT_ROOT / 'references/xbox_one_s_material_validation.json'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


record = json.loads(SOURCE_RECORD.read_text())
expected = record.get('source_glb_sha256')
require(isinstance(expected, str) and len(expected) == 64, f'{SOURCE_RECORD}: missing source_glb_sha256')
source, output = map(Path, sys.argv[sys.argv.index('--') + 1:])
digest = hashlib.sha256(source.read_bytes()).hexdigest()
require(
    digest == expected,
    f'Different source: {source} SHA-256 {digest} does not match {SOURCE_RECORD} ({expected})',
)

import bpy

output.mkdir(parents=True, exist_ok=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
scene = bpy.context.scene
scene.frame_set(0)
scene.view_layers[0].update()
graph = bpy.context.evaluated_depsgraph_get()
originals = list(scene.objects)
meshes = sorted((o for o in originals if o.type == 'MESH'), key=lambda o: o.name)
require(len(meshes) == 16, f'Expected 16 source mesh objects, found {len(meshes)}')
records = []
for index, obj in enumerate(meshes):
    evaluated = obj.evaluated_get(graph)
    mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=graph)
    transform = evaluated.matrix_world.copy()
    mesh.transform(transform)
    if transform.to_3x3().determinant() < 0:
        mesh.flip_normals()
    mesh.calc_loop_triangles()
    vertices = [tuple(v.co) for v in mesh.vertices]
    require(vertices, f'{obj.name}: mesh has no vertices')
    require(
        all(math.isfinite(c) for v in vertices for c in v),
        f'{obj.name}: mesh contains a non-finite vertex',
    )
    name = obj.name.split('_XBox Gamepad')[0]
    stem = f'{index:02d}_{re.sub(r"[^a-zA-Z0-9_-]", "_", name)}_VISUAL_UNCALIBRATED'
    filename = stem + '.obj'
    path = output / filename
    with path.open('w') as handle:
        handle.write('# Visual geometry only. Source-native units; not a collision asset.\n')
        for v in vertices:
            handle.write('v ' + ' '.join(f'{c:.12g}' for c in v) + '\n')
        for t in mesh.loop_triangles:
            handle.write('f ' + ' '.join(str(i+1) for i in t.vertices) + '\n')
    static = bpy.data.objects.new(stem, mesh)
    scene.collection.objects.link(static)
    records.append({
        'name': name, 'source_object': obj.name, 'file': filename,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'vertices': len(vertices), 'triangles': len(mesh.loop_triangles),
        'source_matrix_world': [list(row) for row in transform],
        'bounds_native': [[min(v[i] for v in vertices) for i in range(3)], [max(v[i] for v in vertices) for i in range(3)]],
        'materials': [m.name if m else None for m in mesh.materials],
        'mechanical_pivot': None, 'meters_per_native_unit': None,
        'collision_geometry': None, 'mass_kg': None, 'joint_limits': None,
    })
for obj in originals:
    bpy.data.objects.remove(obj, do_unlink=True)
require(len(list(scene.objects)) == 16, 'Static export did not produce exactly 16 scene objects')
require(len({r['name'] for r in records}) == 16, 'Source mesh names are not unique')
glb = output / 'Xbox_One_S_BatonyRobson_STATIC_VISUAL_UNCALIBRATED.glb'
bpy.ops.export_scene.gltf(filepath=str(glb), export_format='GLB', export_animations=False)
manifest = {
    'source_sha256': digest, 'source': str(source), 'source_frame': 0,
    'source_record': str(SOURCE_RECORD.relative_to(PROJECT_ROOT)),
    'author': 'BatonyRobson', 'license': 'CC-BY-4.0',
    'source_url': 'https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4',
    'status': 'static_visual_parts_only_not_physics',
    'geometry_operation': 'Evaluated source frame 0 baked to world coordinates, no decimation or scale fit',
    'materials': 'Preserved in assembled GLB; OBJ files contain geometry only',
    'meters_per_native_unit': None, 'objects': records,
    'assembled_glb': glb.name, 'assembled_glb_sha256': hashlib.sha256(glb.read_bytes()).hexdigest(),
    'checks': {'pinned_source_hash': True, 'sixteen_unique_parts': True, 'finite_vertices': True},
}
(output / 'inventory.json').write_text(json.dumps(manifest, indent=2))
print('EXPORT_OK: 16 source-derived visual parts; textures retained in GLB; unknown physics null')
