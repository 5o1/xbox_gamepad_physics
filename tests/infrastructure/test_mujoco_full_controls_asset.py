"""Historical MuJoCo tree: source preserved in scripts/archive/mujoco_legacy.

Current backend behavior is covered by tests/backends/mujoco.
"""
import unittest


@unittest.skip("Historical resource tree is retained for provenance only.")
class HistoricalMujocoTreeTest(unittest.TestCase):
    def test_historical_resource_tree(self):
        pass
