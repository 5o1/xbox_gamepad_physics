"""Rendering boundary: shared material, exact 1 mm offset and no actor body build."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import yaml
from teleop.render import add_table_visuals,render_camera_far


class VisualOnlyBuilder:
    def add_box_visual(self,**kwargs):self.visual=kwargs
    def build_render_component(self):return SimpleNamespace(kind='render',visual=self.visual)


class Entity:
    def __init__(self):self.components=[]
    def add_component(self,component):self.components.append(component)
    def set_pose(self,pose):self.pose=pose


class Scene:
    def __init__(self):self.entities=[]
    def create_actor_builder(self):return VisualOnlyBuilder()
    def add_entity(self,entity):self.entities.append(entity)


class GroundRenderTest(unittest.TestCase):
    def test_only_render_components_share_material_and_preserve_table(self):
        fixture=yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/teleop_gripper.yaml').read_text())['teleop']['fixture']
        fake=SimpleNamespace(Entity=Entity,Pose=lambda p,q=None:SimpleNamespace(p=p,q=q),
            render=SimpleNamespace(RenderMaterial=lambda **kwargs:SimpleNamespace(**kwargs)))
        scene=Scene()
        with patch.dict('sys.modules',{'sapien':fake}):entities=add_table_visuals(scene,fixture)
        self.assertEqual(set(entities),{'table','ground'})
        self.assertEqual(entities['table'].pose.p,fixture['table_pose'][:3])
        table,ground=[entities[k].components[0] for k in ('table','ground')]
        self.assertIs(table.visual['material'],ground.visual['material'])
        self.assertEqual(table.visual['material'].base_color,[.28,.31,.34,1])
        self.assertEqual(table.visual['material'].roughness,.85)
        ground_top=entities['ground'].pose.p[2]+ground.visual['half_size'][2]
        table_top=entities['table'].pose.p[2]+table.visual['half_size'][2]
        self.assertAlmostEqual(table_top-ground_top,.001,places=12)
        self.assertEqual([c.kind for e in scene.entities for c in e.components],['render','render'])
        self.assertEqual(render_camera_far(fixture),50.)

    def test_legacy_config_without_display_ground_keeps_old_render(self):
        fixture={'table_half_size_m':[.8,.8,.01],'table_pose':[0,0,-.01,1,0,0,0]}
        fake=SimpleNamespace(Entity=Entity,Pose=lambda p,q=None:SimpleNamespace(p=p,q=q),
            render=SimpleNamespace(RenderMaterial=lambda **kwargs:SimpleNamespace(**kwargs)))
        with patch.dict('sys.modules',{'sapien':fake}):entities=add_table_visuals(Scene(),fixture)
        self.assertEqual(set(entities),{'table'});self.assertEqual(render_camera_far(fixture),3.)
