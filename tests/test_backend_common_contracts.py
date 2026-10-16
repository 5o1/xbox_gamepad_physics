"""Common subsystem boundaries: registration, geometry, appearance and handles."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from xbox_gamepad_physics.backends.registry import backend_spec, selected_nodes, UsageSpec
from xbox_gamepad_physics.builders.build_resources import Node, _selected_graph
from xbox_gamepad_physics.backends.common.appearance import load_appearance
from xbox_gamepad_physics.backends.common.collision import load_collision_sources, iter_frozen_hulls, bind_collision_to_links, internal_contact_policy
from xbox_gamepad_physics.backends.common.handle import validate_env_ids
from xbox_gamepad_physics.backends.common.transforms import compose, inverse, point
from xbox_gamepad_physics.backends.common.model import Pose
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.errors import ResourceError

ROOT=Path(__file__).resolve().parents[1]
RESOURCES=ROOT/'build/resources'


class CommonContractsTest(unittest.TestCase):
    def test_common_import_does_not_load_engines(self):
        code="""import sys
from xbox_gamepad_physics.backends.common import model, calibration, physical, appearance, collision, handle, diagnostics
from xbox_gamepad_physics import acceptance
from xbox_gamepad_physics.backends import registry
assert not {'sapien','mujoco','pxr','isaaclab'} & set(sys.modules)
assert 'torch' not in sys.modules
"""
        subprocess.run([sys.executable,'-c',code],check=True)

    def test_closure_and_platform_requirement_precede_build(self):
        graph=(Node('root',(),(),'root',lambda *_:None),Node('a',(),('root',),'a',lambda *_:None),Node('b',(),(),'b',lambda *_:None))
        self.assertEqual([n.name for n in selected_nodes(graph,('a',))],['root','a'])
        with self.assertRaisesRegex(ResourceError,'isaac_app'):
            _selected_graph(ROOT,ROOT,backends=('isaac',))
        with self.assertRaisesRegex(ResourceError,'not implemented'):
            backend_spec('isaac').require_builder_runtime('isaac_app')
        self.assertEqual(backend_spec('robotwin').builder_runtime,'python')

    def test_query_does_not_prepare_pending_backends(self):
        from xbox_gamepad_physics import resources
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with mock.patch.object(resources,"_resolve_root",return_value=(root,"fixture",None)), mock.patch.object(resources,"_prepare") as prepare:
                for backend in ("robotwin","mujoco","isaac"):
                    self.assertEqual(resources.query_resource_path(backend,"full_controls",must_exist=False),root/backend/'full_controls/manifest.json')
                prepare.assert_not_called()

    def test_instance_collision_and_env_selection_are_scoped(self):
        motion=motion_from_dict(json.loads((RESOURCES/'common/xbox_one_s/motion/full_controls.json').read_text()))
        policy=internal_contact_policy(motion)
        self.assertTrue(all(a[0]=='pad1' and b[0]=='pad1' for a,b in policy.instance_pairs('pad1')))
        self.assertEqual(validate_env_ids([3,1],4),(3,1))
        self.assertEqual(validate_env_ids([],4),())
        for indices in ([1,1],[-1],[4],[True]):
            with self.assertRaises(ValueError):validate_env_ids(indices,4)

    def test_frozen_sources_keep_every_hull_and_link(self):
        sources=load_collision_sources(directory=RESOURCES/'common/xbox_one_s/collision')
        self.assertEqual(len(sources),17)
        hulls=[h for source in sources for h in iter_frozen_hulls(source)]
        self.assertEqual(len(hulls),236)
        self.assertEqual(len({h.hull_id for h in hulls}),236)
        self.assertTrue(all(h.vertices and h.faces for h in hulls))
        motion=motion_from_dict(json.loads((RESOURCES/'common/xbox_one_s/motion/full_controls.json').read_text()))
        instances=bind_collision_to_links(sources,motion)
        self.assertEqual({i.link for i in instances if i.component in ('shell','shell_front_plate')},{'controller_body'})
        self.assertEqual(sum(len(s.triangle_shells) for s in sources),19)

    def test_appearance_is_source_semantics_and_complete_bindings(self):
        manifest=json.loads((RESOURCES/'robotwin/full_controls/manifest.json').read_text())
        appearance=load_appearance(directory=RESOURCES/'common/xbox_one_s/visual',binding=manifest['visual_binding'])
        self.assertEqual(len(appearance.parts),16)
        self.assertEqual(sum(len(p.groups) for p in appearance.parts),20)
        self.assertEqual([m.constant_coverage.value for m in appearance.materials],[1,64/255])
        self.assertEqual(len(appearance.materials[0].textures),5)
        self.assertEqual(appearance.materials[0].textures[0].sampler["minFilter"],9987)
        self.assertTrue(appearance.materials[0].unresolved_differences)
        self.assertTrue(all(p.link!='unbound' for p in appearance.parts))

    def test_transform_roundtrip(self):
        pose=Pose((.1,-.2,.3),(0.,0.,0.,1.))
        sample=(.4,.5,.6)
        for got,expected in zip(point(inverse(pose),point(pose,sample)),sample):self.assertAlmostEqual(got,expected)


if __name__=='__main__':unittest.main()
