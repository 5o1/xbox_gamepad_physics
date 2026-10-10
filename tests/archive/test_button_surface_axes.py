import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'/'archive'))
try:
    import numpy as np
    from button_surface_axes import surface_axes
except ImportError:
    np = None


@unittest.skipIf(np is None, 'Run in GPU NumPy environment')
class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.t=np.array([[[0,0,0],[2,0,0],[2,1,0]],[[0,0,0],[2,1,0],[0,1,0]]],float)

    def test_rectangle_analytic_covariance(self):
        r=surface_axes(self.t)
        np.testing.assert_allclose(r['surface_centroid'],[1,.5,0])
        np.testing.assert_allclose(r['covariance'],np.diag([1/3,1/12,0]),atol=1e-14)

    def test_retriangulation_and_rigid_transform(self):
        subdiv=[]
        for a,b,c in self.t:
            m=(a+b+c)/3
            subdiv.extend([[a,b,m],[b,c,m],[c,a,m]])
        original=surface_axes(self.t)
        np.testing.assert_allclose(surface_axes(subdiv)['covariance'],original['covariance'],atol=1e-14)
        rotation=np.array([[1,0,0],[0,0,-1],[0,1,0]])
        shifted=surface_axes(self.t@rotation.T+[3,4,5])
        np.testing.assert_allclose(shifted['covariance'],rotation@np.array(original['covariance'])@rotation.T,atol=1e-14)

    def test_degenerate_rejected(self):
        for invalid in (np.zeros((1,3,3)),np.full((1,3,3),np.nan),[]):
            with self.assertRaises(ValueError):
                surface_axes(invalid)
