"""SDF is opt-in and keeps live physical/control settings unchanged."""
import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from teleop.server import live_config

ROOT=Path(__file__).resolve().parents[1]
class VariantTest(unittest.TestCase):
    def test_only_selected_collision_changes_in_live_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            mesh=Path(directory)/'shell.obj';mesh.write_text('v 0 0 -0.03\nv 0 0 0.03\n')
            with patch('xbox_gamepad_physics.resources.resource_path',return_value=mesh),patch('teleop.site.require',return_value=directory):
                default=live_config(ROOT/'configs/teleop_gripper.yaml')
                coacd=live_config(ROOT/'configs/teleop_gripper.yaml',collision='coacd')
        self.assertEqual(default['gamepad']['collision'],'sdf')
        self.assertEqual(coacd['gamepad']['collision'],'coacd')
        coacd['gamepad']['collision']='sdf'
        self.assertEqual(coacd,default)
        self.assertEqual(default['scene']['timestep'],.004)
        self.assertTrue(default['gamepad']['fixed_root'])
