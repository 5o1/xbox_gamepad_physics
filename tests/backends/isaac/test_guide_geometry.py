"""Analytic checks for neutral clearance measurements, independent of engines."""
import numpy as np
from xbox_gamepad_physics.isaac.guide_clearance import _point_distances,_ray_hits


def test_triangle_face_edge_vertex_distances():
    tri=np.array([[[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]]])
    points=np.array([[.25,.25,2.],[2.,0.,0.],[.75,.75,0.]])
    np.testing.assert_allclose(_point_distances(points,tri),[2.,1.,np.sqrt(.125)],rtol=1e-12,atol=1e-14)


def test_ray_shared_triangle_edge_is_one_surface_crossing():
    triangles=np.array([[[-1.,-1.,0.],[1.,-1.,0.],[1.,1.,0.]],
                        [[-1.,-1.,0.],[1.,1.,0.],[-1.,1.,0.]]])
    np.testing.assert_allclose(_ray_hits(np.array([0.,0.,2.]),np.array([0.,0.,-1.]),triangles),[2.],rtol=0,atol=1e-14)
