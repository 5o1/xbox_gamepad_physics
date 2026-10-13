"""Report 8.3 final metric, adapted from the 20261011 sweep (no union-face filter)."""
import time
import numpy as np
from scipy.spatial import ConvexHull
from .distance import TriangleDistance

def sample(mesh,seed,density=4):
 # Each face receives at least ceil(area * 4 points/mm2), uniformly by area.
 count=np.maximum(1,np.ceil(mesh.area_faces*density*1e6).astype(int)); ids=np.repeat(np.arange(len(mesh.faces)),count)
 rng=np.random.default_rng(seed); uv=rng.random((len(ids),2)); over=uv.sum(axis=1)>1; uv[over]=1-uv[over]
 tri=mesh.triangles[ids]; return tri[:,0]+uv[:,0,None]*(tri[:,1]-tri[:,0])+uv[:,1,None]*(tri[:,2]-tri[:,0])


def winding(points,triangles,point_batch=128,triangle_batch=1024):
 output=np.empty(len(points));start=time.perf_counter()
 for lo in range(0,len(points),point_batch):
  pts=points[lo:lo+point_batch];sums=np.zeros(len(pts))
  for j in range(0,len(triangles),triangle_batch):
   t=triangles[j:j+triangle_batch];a=t[None,:,0,:]-pts[:,None,:];b=t[None,:,1,:]-pts[:,None,:];c=t[None,:,2,:]-pts[:,None,:]
   la=np.linalg.norm(a,axis=2);lb=np.linalg.norm(b,axis=2);lc=np.linalg.norm(c,axis=2)
   numerator=np.einsum('ijk,ijk->ij',a,np.cross(b,c))
   denominator=la*lb*lc+np.einsum('ijk,ijk->ij',a,b)*lc+np.einsum('ijk,ijk->ij',b,c)*la+np.einsum('ijk,ijk->ij',c,a)*lb
   sums+=np.sum(2*np.arctan2(numerator,denominator),axis=1)
  output[lo:lo+len(pts)]=sums/(4*np.pi)
 return output

def covered(points,hulls,tolerance_m=1e-5):
 good=np.zeros(len(points),bool)
 for h in hulls:
  e=ConvexHull(h.vertices).equations;b=h.bounds;ids=np.flatnonzero(~good & np.all(points>=b[0]-tolerance_m,axis=1)&np.all(points<=b[1]+tolerance_m,axis=1))
  for start in range(0,len(ids),1024):
   ix=ids[start:start+1024];good[ix]=np.all(points[ix]@e[:,:3].T+e[:,3]<=tolerance_m,axis=1)
 return good


def stats_mm(values):
    values = np.asarray(values)
    if not len(values):
        return dict(max_mm=0., p95_mm=0., mean_mm=0., count=0)
    return dict(max_mm=float(values.max()), p95_mm=float(np.percentile(values,95)),
                mean_mm=float(values.mean()), count=len(values))


def error_field(source, hulls, density=4, source_seed=100, hull_seed=200, coverage_tolerance_m=1e-5, winding_inside_threshold=.5, hotspot_threshold_mm=.3):
    source_points = sample(source, source_seed, density)
    pieces = [sample(h, hull_seed+i, density) for i,h in enumerate(hulls)]
    points = np.concatenate(pieces)
    labels = np.concatenate([np.full(len(p),i) for i,p in enumerate(pieces)])
    w = winding(points, source.triangles)
    outside = w <= winding_inside_threshold
    outward = np.zeros(len(points))
    outward[outside] = TriangleDistance(source.triangles).query(points[outside])[0]*1000
    cover = covered(source_points,hulls,coverage_tolerance_m)
    inward = np.zeros(len(source_points))
    if (~cover).any():
        inward[~cover] = TriangleDistance(np.concatenate([h.triangles for h in hulls])).query(source_points[~cover])[0]*1000
    summary = dict(metric_definition='reviewer_final_GWN_10um_exact_triangle_distance',
                   outward=stats_mm(outward[outside]), inward=stats_mm(inward),
                   source_samples=len(source_points), source_uncovered_samples=int((~cover).sum()),
                   hull_surface_samples=len(points), outside_samples=int(outside.sum()),
                   hulls=[dict(index=i, vertices=len(h.vertices), outward=stats_mm(outward[(labels==i)&outside]),
                               hotspot_samples=int(((labels==i)&(outward>hotspot_threshold_mm)).sum())) for i,h in enumerate(hulls)])
    arrays=dict(points=points,labels=labels,outward_mm=outward,winding=w,source=source_points,
                inward_mm=inward,source_covered=cover)
    return summary,arrays
