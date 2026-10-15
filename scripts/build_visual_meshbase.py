#!/usr/bin/env python3
"""Regenerate the reviewed Xbox One S visual mesh base for maintainer review.

This command is independent of normal builds. It accepts only the checkout's
reviewed STATIC_VISUAL GLB and inventory. NumPy and Pillow are required.
"""
from __future__ import annotations

import argparse
import copy
import io
import itertools
import json
from collections import defaultdict
from pathlib import Path
import shutil
import struct

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REL = Path("assets/xbox_one_s/visual/Xbox_One_S_BatonyRobson_STATIC_VISUAL_UNCALIBRATED.glb")
INVENTORY_REL = Path("assets/xbox_one_s/visual/inventory.json")
SNAPSHOT = ROOT / "assets/xbox_one_s/visual_meshbase"
ARCHIVES = ROOT / "assets/xbox_one_s/archive"
EXPERIMENT = "build/experiments/visual_meshbase_20261015"
SOURCE_URL = "https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4"
ALPHA_RULE = {
    "version": 2,
    "exact_below": 255,
    "halo_below": 250,
    "halo_texels": 1,
    "coverage": "Closed triangle/texel-square SAT, including touching and degenerate UVs",
    "uv_origin": "Top left; no image or UV flip",
    "precision": "float64 UV times original image resolution; SAT projection tolerance 1e-9 texel units",
    "enumeration": "floor(triangle minimum)-1 through ceil(triangle maximum), inclusive",
    "wrap": "REPEAT modulo original image dimensions on both axes",
    "halo": "Union of 3x3 texel neighbourhoods of exact covered cells, including centre",
    "decision": "BLEND if exact_min<255 OR halo_min<250; otherwise OPAQUE",
    "mixed_diagnostic": "exact_min<=242 AND exact_max>=253; report without subdivision",
    "subdivision": False,
    "merge_vertices": False,
    "revision_basis": "Owner ruling 3, after observing v1. Under the stated bilinear halo-weight<=1/2 assumption, alpha>=250 loses at most (255-250)/255/2, about 0.9804%. Not fitted to the observed 253; not a general mip/anisotropy guarantee.",
}

def read_glb(path):
    b = path.read_bytes()
    magic, version, size = struct.unpack_from('<III', b)
    assert (magic, version, size) == (0x46546C67, 2, len(b))
    n, kind = struct.unpack_from('<II', b, 12)
    assert kind == 0x4E4F534A
    length, kind = struct.unpack_from('<II', b, 20+n)
    assert kind == 0x004E4942
    return json.loads(b[20:20+n]), b[28+n:28+n+length]

def accessor(d, binary, index):
    a = d['accessors'][index]
    assert 'sparse' not in a
    v = d['bufferViews'][a['bufferView']]
    types = {5121: '<u1', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
    count = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a['type']]
    dtype = np.dtype(types[a['componentType']])
    return np.ndarray((a['count'], count), dtype=dtype, buffer=binary,
                      offset=v.get('byteOffset', 0)+a.get('byteOffset', 0),
                      strides=(v.get('byteStride', count*dtype.itemsize), dtype.itemsize))

def image_bytes(d, binary, index):
    v = d['bufferViews'][d['images'][index]['bufferView']]
    return binary[v.get('byteOffset', 0):v.get('byteOffset', 0)+v['byteLength']]

def covered_texels(tri, width, height):
    """Exact triangle-square SAT up to float64 roundoff, including touching."""
    tri = tri.astype(np.float64) * [width, height]
    lower = np.floor(tri.min(axis=0)).astype(int)-1
    upper = np.ceil(tri.max(axis=0)).astype(int)
    x, y = np.meshgrid(np.arange(lower[0], upper[0]+1), np.arange(lower[1], upper[1]+1))
    x, y = x.ravel(), y.ravel()
    centers = np.column_stack((x+.5, y+.5))
    keep = np.ones(len(x), dtype=bool)
    axes = [np.array([1., 0.]), np.array([0., 1.])]
    edges = np.roll(tri, -1, axis=0)-tri
    axes += [np.array([-edge[1], edge[0]]) for edge in edges if np.any(edge)]
    for axis in axes:
        projected = tri @ axis
        box = centers @ axis
        radius = .5*np.abs(axis).sum()
        keep &= (box+radius >= projected.min()-1e-9) & (box-radius <= projected.max()+1e-9)
    return x[keep], y[keep]

def seam_gate(document, binary, partitions):
    boundaries, unsafe_edges, shared_vertices = [], [], []
    per_part = []
    for mi, mesh in enumerate(document['meshes']):
        p = mesh['primitives'][0]
        faces = accessor(document, binary, p['indices']).reshape(-1, 3)
        positions = accessor(document, binary, p['attributes']['POSITION'])
        classes = partitions[mi]
        edges, incident = defaultdict(list), defaultdict(list)
        for fi, face in enumerate(faces):
            for vertex in face:
                incident[int(vertex)].append(fi)
            for a, b in zip(face, np.roll(face, -1)):
                pa, pb = tuple(positions[a].tolist()), tuple(positions[b].tolist())
                edge_key = tuple(sorted((pa, pb)))
                edges[edge_key].append((fi, int(a), int(b)))
        part_boundaries = []
        for geometry, group in edges.items():
            for one, two in itertools.combinations(group, 2):
                if classes[one[0]] == classes[two[0]]:
                    continue
                shared = sorted(set(one[1:]) & set(two[1:]))
                rec = dict(mesh_index=mi, part=document['nodes'][mi]['name'],
                           faces=[one[0], two[0]], alpha_modes=['BLEND' if classes[x[0]] else 'OPAQUE' for x in (one, two)],
                           vertex_indices=[list(one[1:]), list(two[1:])], positions=geometry,
                           shared_original_indices=shared, existing_seam=not shared)
                boundaries.append(rec); part_boundaries.append(rec)
                if shared:
                    unsafe_edges.append(rec)
        part_shared = []
        for vertex, fi in incident.items():
            opaque = sorted(set(f for f in fi if not classes[f]))
            blend = sorted(set(f for f in fi if classes[f]))
            if opaque and blend:
                rec = dict(mesh_index=mi, part=document['nodes'][mi]['name'], vertex=vertex,
                           position=positions[vertex].tolist(), opaque_faces=opaque, blend_faces=blend)
                shared_vertices.append(rec); part_shared.append(rec)
        per_part.append(dict(mesh_index=mi, name=document['nodes'][mi]['name'],
                             boundary_pairs=len(part_boundaries),
                             unsafe_boundary_pairs=sum(not r['existing_seam'] for r in part_boundaries),
                             shared_vertices_cut=len(part_shared)))
    return dict(passed=not unsafe_edges and not shared_vertices,
                algorithm='Exact-position edge grouping within each original primitive; every unlike-class pair must have disjoint original endpoint indices. Also reject original vertex indices incident to both classes.',
                coordinate_tolerance=0, merge_vertices=False, boundary_pairs=len(boundaries),
                existing_seam_pairs=sum(r['existing_seam'] for r in boundaries),
                unsafe_edges=unsafe_edges, shared_vertices_cut=shared_vertices,
                boundaries=boundaries, parts=per_part)


def classify(document, binary, inventory):
    """Recompute v2 coverage from the original image, never cached face statistics."""
    if len(document['materials']) != 1 or document['materials'][0].get('alphaMode') != 'BLEND':
        raise ValueError('expected the reviewed single BLEND material')
    material = document['materials'][0]
    texture = document['textures'][material['pbrMetallicRoughness']['baseColorTexture']['index']]
    sampler = document['samplers'][texture['sampler']]
    if sampler.get('wrapS', 10497) != 10497 or sampler.get('wrapT', 10497) != 10497:
        raise ValueError('the reviewed rule requires REPEAT wrapping')
    alpha = np.asarray(Image.open(io.BytesIO(image_bytes(document, binary, texture['source']))).convert('RGBA'))[:, :, 3]
    height, width = alpha.shape
    if len(inventory['objects']) != len(document['meshes']):
        raise ValueError('inventory and reviewed meshes disagree')
    partitions, parts, blend_ranges = [], [], []
    for mi, mesh in enumerate(document['meshes']):
        if len(mesh['primitives']) != 1 or mesh['primitives'][0].get('mode', 4) != 4:
            raise ValueError('expected one triangle primitive per reviewed part')
        primitive = mesh['primitives'][0]
        faces = accessor(document, binary, primitive['indices']).reshape(-1, 3)
        node = next(node for node in document['nodes'] if node.get('mesh') == mi)
        item = inventory['objects'][mi]
        if node['name'] != Path(item['file']).stem or len(faces) != item['triangles']:
            raise ValueError('reviewed part names or triangle counts disagree with inventory')
        uv = accessor(document, binary, primitive['attributes']['TEXCOORD_0'])
        classes, mixed = [], 0
        for face in faces:
            x, y = covered_texels(uv[face], width, height)
            values = alpha[y % height, x % width]
            halo = np.concatenate([alpha[(y + dy) % height, (x + dx) % width]
                                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
            blend = bool(values.min() < 255 or halo.min() < 250)
            classes.append(blend)
            mixed += int(values.min() <= 242 and values.max() >= 253)
            if blend:
                blend_ranges.append((int(values.min()), int(values.max())))
        classes = np.asarray(classes, dtype=bool)
        partitions.append(classes)
        parts.append(dict(name=node['name'], mesh_name=mesh['name'], triangles=len(faces),
                          opaque=int((~classes).sum()), blend=int(classes.sum()), mixed=mixed))
    coverage = dict(faces=len(blend_ranges), exact_alpha_min=min(x[0] for x in blend_ranges),
                    exact_alpha_max=max(x[1] for x in blend_ranges), image_size=[width, height])
    return partitions, parts, coverage


def split(document, binary, partitions):
    """Append only index subsets; retain every original attribute and image byte."""
    result = copy.deepcopy(document)
    result['materials'] = []
    for mode in ('OPAQUE', 'BLEND'):
        material = copy.deepcopy(document['materials'][0])
        material.update(alphaMode=mode, name=material['name'] + '_' + mode)
        result['materials'].append(material)
    packed = bytearray(binary)
    for mi, mesh in enumerate(document['meshes']):
        primitive = mesh['primitives'][0]
        faces = accessor(document, binary, primitive['indices']).reshape(-1, 3)
        primitives = []
        for mat, mask in enumerate((~partitions[mi], partitions[mi])):
            if not np.any(mask):
                continue
            indices = faces[mask].astype('<u4').ravel()
            packed.extend(b'\0' * ((-len(packed)) % 4))
            vi, ai = len(result['bufferViews']), len(result['accessors'])
            result['bufferViews'].append(dict(buffer=0, byteOffset=len(packed), byteLength=indices.nbytes, target=34963))
            packed.extend(indices.tobytes())
            result['accessors'].append(dict(bufferView=vi, componentType=5125, count=len(indices), type='SCALAR',
                                            min=[int(indices.min())], max=[int(indices.max())]))
            item = copy.deepcopy(primitive)
            item.update(indices=ai, material=mat)
            primitives.append(item)
        result['meshes'][mi]['primitives'] = primitives
    result['buffers'][0]['byteLength'] = len(packed)
    return result, packed


def verify_k1(source, binary, result, packed, partitions):
    """Restore original face order and compare source data directly, without digests."""
    if packed[:len(binary)] != binary:
        raise ValueError('K1: original binary prefix changed')
    for key in ('nodes', 'scenes', 'images', 'textures', 'samplers'):
        if source[key] != result[key]:
            raise ValueError(f'K1: {key} changed')
    for key in ('accessors', 'bufferViews'):
        if result[key][:len(source[key])] != source[key]:
            raise ValueError(f'K1: original {key} changed')
    for mi, mesh in enumerate(source['meshes']):
        original = mesh['primitives'][0]
        faces = accessor(source, binary, original['indices']).reshape(-1, 3)
        restored, seen = np.empty_like(faces), np.zeros(len(faces), dtype=int)
        if mesh['name'] != result['meshes'][mi]['name']:
            raise ValueError('K1: mesh name changed')
        for primitive in result['meshes'][mi]['primitives']:
            mask = partitions[mi] if primitive['material'] else ~partitions[mi]
            restored[mask] = accessor(result, packed, primitive['indices']).reshape(-1, 3)
            seen[mask] += 1
            if primitive['attributes'] != original['attributes']:
                raise ValueError('K1: attribute references changed')
            for index in original['attributes'].values():
                if accessor(source, binary, index).tobytes() != accessor(result, packed, index).tobytes():
                    raise ValueError('K1: attribute data changed')
        if not np.all(seen == 1) or not np.array_equal(restored, faces):
            raise ValueError('K1: face partition is not a disjoint exact cover')
    for i in range(len(source['images'])):
        if image_bytes(source, binary, i) != image_bytes(result, packed, i):
            raise ValueError('K1: embedded image changed')


def material_description(document, result, coverage):
    material = document['materials'][0]
    pbr = material['pbrMetallicRoughness']
    extension = material.get('extensions', {})
    specular = extension.get('KHR_materials_specular', {})
    roles = {}
    for name, info, channels, space in (
        ('baseColor', pbr['baseColorTexture'], 'RGB sRGB; A linear coverage', 'sRGB RGB / linear A'),
        ('emissive', material['emissiveTexture'], 'RGB', 'sRGB'),
        ('normal', material['normalTexture'], 'RGB tangent-space normal', 'linear'),
        ('occlusion', material['occlusionTexture'], 'R', 'linear'),
        ('roughness', pbr['metallicRoughnessTexture'], 'G', 'linear'),
        ('metallic', pbr['metallicRoughnessTexture'], 'B', 'linear'),
        ('specularColor', specular['specularColorTexture'], 'RGB', 'sRGB'),
    ):
        roles[name] = dict(texture=info['index'], channels=channels, color_space=space)
    return dict(
        status='review_candidate', source='reviewed STATIC_VISUAL, not reconstructed author material',
        authored_material=material, materials=result['materials'],
        **{key: document[key] for key in ('textures', 'images', 'samplers')},
        texture_roles=roles,
        factors=dict(baseColor=pbr.get('baseColorFactor', [1, 1, 1, 1]),
                     metallic=pbr.get('metallicFactor', 1), roughness=pbr.get('roughnessFactor', 1),
                     normalScale=material['normalTexture'].get('scale', 1),
                     emissive=material.get('emissiveFactor', [0, 0, 0]),
                     emissiveStrength=extension['KHR_materials_emissive_strength']['emissiveStrength'],
                     occlusionStrength=material['occlusionTexture'].get('strength', 1),
                     specularFactor=specular.get('specularFactor', 1),
                     specularColorFactor=specular.get('specularColorFactor', [1, 1, 1])),
        factor_evidence='Explicit STATIC_VISUAL values; omitted values are glTF/KHR defaults, not simulator defaults.',
        doubleSided=material.get('doubleSided', False), physical_parameters=None,
        constant_opacity=dict(
            material='BLEND', value=64 / 255, numerator=64, denominator=255, units='dimensionless linear coverage',
            source=dict(description='V2 exact UV coverage: all 256 BLEND faces have alpha_min=alpha_max=64.',
                        statistics=coverage, evidence=EXPERIMENT + '/ruling5/opacity_evidence.json'),
            usage='For backends routing transparent passes by constant opacity, including SAPIEN raster and MuJoCo classic.',
            sapien='SAPIEN 3.0.3 material.base_color.a selects the pass. With a base-color texture, gbuffer1.frag:85-94,205 takes texture RGBA directly and does not multiply constant alpha; keep source RGBA and visibility 1.',
            sapien_source='https://github.com/haosulab/sapien-vulkan-2/blob/2ad24e1e96d88d3dd00fb1a7821ffcef42ab1ed9/src/renderer/renderer.cpp#L765',
            shader_evidence=EXPERIMENT + '/ruling4/sources/installed_shader/gbuffer1.frag',
            mujoco='Use RGB-only base texture plus BLEND material rgba.a=64/255, applied once.',
            gltf='Keep GLB baseColorFactor.a=1: source texture already contains 64/255. Do not multiply twice; Cycles GLB is unchanged.'),
        specular_note='STATIC_VISUAL uses KHR_materials_specular.specularColorTexture (RGB sRGB); the author GLB uses specularTexture (A linear). This snapshot preserves STATIC_VISUAL. Reconciliation is deferred.',
        scope='Appearance only; no contact, dynamics, kinematic, or RL validation.')


def readme(frozen=False):
    status = 'Frozen, owner-reviewed snapshot (ruling 6, 2026-10-16).' if frozen else 'Regenerated review candidate; adoption requires owner review.'
    return f'''# Xbox One S visual mesh base

Author: BatonyRobson. Work: Xbox One S Controller/Gamepad (Animated).
Source: {SOURCE_URL}
License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

{status}
This appearance base retains the reviewed STATIC_VISUAL geometry and textures for
backend appearance derivation. This freeze is repository-only: the build DAG,
loaders and resource packages do not consume it yet. Normal builds do not run
the maintainer command. It is not a collision or validated physical model.

Files: `visual_meshbase.glb`, `materials.json`, `manifest.json`, `README.md`.
The GLB preserves node names/transforms, vertices, normals, UVs and image bytes.
Only face index groups and the two material names/alphaMode differ from the
STATIC_VISUAL source. Empty groups are omitted. No rebaking or subdivision.

Generation: closed triangle/texel-square UV coverage, including boundary contact,
with REPEAT wrapping. A face is BLEND if exact alpha<255 or a one-texel 3x3 halo
contains alpha<250. Otherwise it is OPAQUE. Every split must pass the original
shared-index seam gate before output; it must never cut a shared vertex.
All parameters and provenance are in `manifest.json`.

The 256 BLEND faces cover alpha 64 only. `materials.json` records 64/255 for native
constant-opacity pass routing. Preserve source RGBA in SAPIEN 3.0.3: its textured
shader takes texture alpha directly. MuJoCo classic instead uses RGB plus the
material constant. Never multiply the GLB texture alpha by 64/255 a second time.
STATIC_VISUAL specularColorTexture differs from the author GLB specularTexture;
this snapshot retains STATIC_VISUAL, with reconciliation deferred.

Maintainer review command, from the checkout root (NumPy and Pillow required):

```sh
python3 scripts/build_visual_meshbase.py --output build/review/visual_meshbase
```

Revision rule: rerun this maintainer script; archive the intact old version under
`assets/xbox_one_s/archive/` before replacing the formal snapshot. The script
requires a new archive destination when overwriting the formal directory:

```sh
python3 scripts/build_visual_meshbase.py --output assets/xbox_one_s/visual_meshbase --archive assets/xbox_one_s/archive/visual_meshbase_PREVIOUS_REVIEW
```

Regeneration creates a review candidate, not automatic visual approval. Repeat
the import/render gates and obtain owner review before declaring a new freeze.
Prior gate results are historical evidence, not automatic approval of new bytes.
Evidence and the accepted 2026-10-16 decision are listed in the manifest.
Retain attribution, license and modification notes on distribution.
No author endorsement is claimed.
'''


def build(output, source=ROOT / SOURCE_REL, archive=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source != (ROOT / SOURCE_REL).resolve():
        raise ValueError('only the reviewed STATIC_VISUAL input is accepted')
    formal = output == SNAPSHOT.resolve()
    if output.is_relative_to(ROOT / 'assets') and not formal:
        raise ValueError('review outputs must be outside assets; formal output has a fixed location')
    archive = Path(archive).resolve() if archive is not None else None
    if output.exists():
        if not formal or archive is None:
            raise ValueError('output exists; replacing the formal snapshot requires --archive')
        if not archive.is_relative_to(ARCHIVES.resolve()) or archive == ARCHIVES.resolve() or archive.exists():
            raise ValueError('archive must be a new directory under assets/xbox_one_s/archive')
    elif archive is not None:
        raise ValueError('no existing formal snapshot at output to archive')
    document, binary = read_glb(source)
    inventory = json.loads((ROOT / INVENTORY_REL).read_text())
    partitions, parts, coverage = classify(document, binary, inventory)
    gate = seam_gate(document, binary, partitions)
    if not gate['passed']:
        raise ValueError('unsafe original shared vertices at material boundary: ' + json.dumps(gate))
    if coverage['exact_alpha_min'] != 64 or coverage['exact_alpha_max'] != 64 or coverage['faces'] != 256:
        raise ValueError('covered alpha no longer matches the reviewed constant-opacity source; review required')
    result, packed = split(document, binary, partitions)
    verify_k1(document, binary, result, packed, partitions)
    js = json.dumps(result, separators=(',', ':')).encode()
    js += b' ' * ((-len(js)) % 4)
    packed.extend(b'\0' * ((-len(packed)) % 4))
    raw = struct.pack('<III', 0x46546C67, 2, 28 + len(js) + len(packed))
    raw += struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(packed), 0x004E4942) + packed
    manifest = dict(
        asset_id='xbox_one_s', stage='visual_meshbase', frozen=False, status='review_candidate',
        author=inventory['author'], license=inventory['license'], source_url=inventory['source_url'],
        derived_from=dict(source=SOURCE_REL.as_posix(), inventory=INVENTORY_REL.as_posix(),
                          generator='scripts/build_visual_meshbase.py', algorithm_version=2),
        alpha_rule=ALPHA_RULE, parts=parts,
        statistics=dict(triangles=sum(x['triangles'] for x in parts), opaque=sum(x['opaque'] for x in parts),
                        blend=sum(x['blend'] for x in parts), mixed=sum(x['mixed'] for x in parts),
                        blend_coverage=coverage),
        seam_gate={**gate, 'required_for_every_future_split': True},
        checks=dict(k1=dict(passed=True, method='Direct binary prefix, attribute, image, node and disjoint face-cover comparison'),
                    seam_gate=dict(passed=True)),
        evidence=dict(algorithm=EXPERIMENT + '/ALGORITHM_V2_PREREGISTERED.md',
                      report=EXPERIMENT + '/REPORT.md', ruling3=EXPERIMENT + '/ruling3/V2_REPORT.md',
                      ruling5=EXPERIMENT + '/ruling5/REPORT.md'),
        coordinate_frame='unchanged glTF Y up, native units', meters_per_native_unit=None,
        changes='Split original triangle indices into OPAQUE/BLEND without changing source attributes, images or nodes.',
        previous_versions=[], adoption='Repository-only; not consumed by DAG, loaders or resource packages.',
        files=['visual_meshbase.glb', 'materials.json', 'manifest.json', 'README.md'])
    if output.exists():
        shutil.copytree(output, archive)
        shutil.rmtree(output)
        manifest['previous_versions'] = [archive.relative_to(ROOT).as_posix()]
    output.mkdir(parents=True)
    (output / 'visual_meshbase.glb').write_bytes(raw)
    (output / 'materials.json').write_text(json.dumps(material_description(document, result, coverage), indent=2) + '\n')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'README.md').write_text(readme())
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new review directory; normal builds never run this command')
    parser.add_argument('--source', type=Path, default=ROOT / SOURCE_REL, help='only the reviewed checkout STATIC_VISUAL path is accepted')
    parser.add_argument('--archive', type=Path, help='new archive directory required before overwriting the formal snapshot')
    args = parser.parse_args()
    manifest = build(args.output, args.source, args.archive)
    print(json.dumps(dict(statistics=manifest['statistics'], seam_gate=manifest['seam_gate']['passed'], k1=True)))


if __name__ == '__main__':
    main()
