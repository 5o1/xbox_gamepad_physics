"""Verify reviewed face groups reach generated resources and native attachment."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from xbox_gamepad_physics.builders import build_resources
from xbox_gamepad_physics.builders.usage import document_outputs, README, USAGE
from xbox_gamepad_physics.robotwin import visual
from xbox_gamepad_physics import resources

ROOT = Path(__file__).resolve().parents[2]
HAS_BUILD = all(importlib.util.find_spec(name) for name in ('PIL', 'numpy'))


class UsageGuidanceTests(unittest.TestCase):
    def test_generated_guidance_is_deterministic_and_urdf_is_parseable(self):
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'visual').mkdir()
            (root / 'collision').mkdir()
            (root / 'collision/part.obj').write_text('v 0 0 0\n')
            (root / 'manifest.json').write_text('{}')
            (root / 'mobility.urdf').write_text('<?xml version="1.0"?>\n<robot name="xbox_one_s"/>\n')
            document_outputs(root)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            document_outputs(root)
            after = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            for relative in ('README.md', 'visual/README.md', 'collision/README.md'):
                self.assertEqual((root / relative).read_text(), README)
            self.assertEqual(json.loads((root / 'manifest.json').read_text())['usage'], USAGE)
            text = (root / 'mobility.urdf').read_text()
            self.assertLess(text.index('load_into_scene'), text.index('<robot'))
            self.assertEqual(ET.parse(root / 'mobility.urdf').getroot().tag, 'robot')

    def test_sim_visual_tracks_frozen_inputs(self):
        node = next(n for n in build_resources.nodes(ROOT) if n.name == 'sim_visual')
        for name in ('visual_meshbase.glb', 'materials.json', 'manifest.json'):
            self.assertIn(str(ROOT / 'assets/xbox_one_s/visual_meshbase' / name), node.inputs)
        self.assertFalse(any(name.endswith('README.md') for name in node.inputs))

    def test_presence_check_includes_group_meshes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'common/xbox_one_s/visual'
            target.mkdir(parents=True)
            (target / 'manifest.json').write_text(json.dumps({'parts': [
                {'file': 'whole.gltf', 'groups': [{'file': 'blend.gltf'}]}]}))
            self.assertIn('common/xbox_one_s/visual/blend.gltf', resources.missing_resources(root))


@unittest.skipUnless(HAS_BUILD, 'visual export needs optional [build] NumPy and Pillow')
class VisualMeshbaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from xbox_gamepad_physics.builders.export_sim_visual_assets import build, read_glb
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.output = Path(cls.temporary.name) / 'visual'
        build(cls.output, inputs=ROOT)
        cls.manifest = json.loads((cls.output / 'manifest.json').read_text())
        cls.geometry, cls.binary = read_glb(ROOT / 'assets/xbox_one_s/visual_meshbase/visual_meshbase.glb')

    @staticmethod
    def _accessor_bytes(document, binary, index):
        item = document['accessors'][index]
        view = document['bufferViews'][item['bufferView']]
        start = view.get('byteOffset', 0) + item.get('byteOffset', 0)
        count = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[item['type']]
        size = {5121: 1, 5123: 2, 5125: 4, 5126: 4}[item['componentType']]
        return binary[start:start + item['count'] * count * size]

    def test_groups_preserve_original_attributes_indices_and_texture_bytes(self):
        counts = Counter()
        binary = (self.output / 'meshes.bin').read_bytes()
        parts = {p['name']: p for p in self.manifest['parts']}
        for node in self.geometry['nodes']:
            part = parts[node['name']]
            primitives = self.geometry['meshes'][node['mesh']]['primitives']
            self.assertEqual(len(part['groups']), len(primitives))
            self.assertEqual(part['triangles'], sum(g['triangles'] for g in part['groups']))
            for group, original in zip(part['groups'], primitives):
                counts[group['alpha_mode']] += group['triangles']
                expected = 64 / 255 if group['alpha_mode'] == 'BLEND' else 1
                self.assertEqual(group['constant_opacity'], expected)
                document = json.loads((self.output / group['file']).read_text())
                exported = document['meshes'][0]['primitives'][0]
                for name, index in original['attributes'].items():
                    self.assertEqual(self._accessor_bytes(self.geometry, self.binary, index),
                                     self._accessor_bytes(document, binary, exported['attributes'][name]))
                self.assertEqual(self._accessor_bytes(self.geometry, self.binary, original['indices']),
                                 self._accessor_bytes(document, binary, exported['indices']))
        self.assertEqual(counts, {'OPAQUE': 6590, 'BLEND': 256})
        from xbox_gamepad_physics.builders.export_sim_visual_assets import read_glb
        authored, source = read_glb(ROOT / 'assets/xbox_one_s/source/xbox_one_s_controllergamepad_animated.glb')
        for image, exported in zip(authored['images'], self.manifest['source_textures']):
            view = authored['bufferViews'][image['bufferView']]
            start = view.get('byteOffset', 0)
            self.assertEqual((self.output / exported['file']).read_bytes(), source[start:start + view['byteLength']])

    def test_attachment_uses_group_opacity_without_changing_link_binding(self):
        class Pose:
            def __init__(self, **kwargs): self.values = kwargs
            def __mul__(self, other): return (self.values, other.values)
        class Material:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        class Body:
            def __init__(self): self.shapes = []
            def attach(self, shape): self.shapes.append(shape)
        class Entity:
            def __init__(self): self.components = []
            def add_component(self, body): self.components.append(body)
        def shape(path, **kwargs): return SimpleNamespace(path=path, **kwargs)
        render = SimpleNamespace(RenderMaterial=Material, RenderTexture2D=lambda path, **kwargs: path,
                                 RenderBodyComponent=Body, RenderShapeTriangleMesh=shape)
        sapien = SimpleNamespace(render=render, Pose=Pose)
        parts = self.manifest['parts']
        moving = parts[0]['name']
        binding = {'root_link': 'root', 'static_parts': [p['name'] for p in parts[1:]],
                   'moving_parts': {moving: {'link': 'button', 'pivot_m_source_frame': [1, 2, 3]}}}
        links = [SimpleNamespace(name=name, entity=Entity()) for name in ('root', 'button')]
        articulation = SimpleNamespace(get_links=lambda: links)
        with mock.patch.object(visual, 'import_module', return_value=sapien):
            result = visual.attach_visual_to_articulation(articulation, binding, directory=self.output)
        self.assertEqual(set(result.components), {'root', 'button'})
        all_shapes = [shape for component in result.components.values() for shape in component.shapes]
        self.assertEqual(len(all_shapes), 20)
        self.assertEqual(Counter(s.material.base_color[3] for s in all_shapes), {1: 16, 64 / 255: 4})
        self.assertEqual(len(result.components['button'].shapes), 2)
        for s in result.components['button'].shapes:
            self.assertEqual(s.local_pose[0]['p'], [-1.0, -2.0, -3.0])
        opaque = next(s.material for s in all_shapes if s.material.base_color[3] == 1)
        blend = next(s.material for s in all_shapes if s.material.base_color[3] != 1)
        self.assertIs(opaque.base_color_texture, blend.base_color_texture)


if __name__ == '__main__':
    unittest.main()
