import numpy as np
from scipy.spatial import cKDTree

def squared_distance(point,tri):
 # Orthogonal projection to the face, or the nearest of its three closed segments.
 a=tri[...,0,:];b=tri[...,1,:];c=tri[...,2,:];ab=b-a;ac=c-a;ap=point-a
 d00=np.einsum('...i,...i->...',ab,ab);d01=np.einsum('...i,...i->...',ab,ac);d11=np.einsum('...i,...i->...',ac,ac)
 d20=np.einsum('...i,...i->...',ap,ab);d21=np.einsum('...i,...i->...',ap,ac)
 denom=d00*d11-d01*d01;safe=np.where(denom>0,denom,1.);u=(d11*d20-d01*d21)/safe;v=(d00*d21-d01*d20)/safe
 projected=a+u[...,None]*ab+v[...,None]*ac;delta=point-projected;face=np.einsum('...i,...i->...',delta,delta)
 inside=(denom>0)&(u>=0)&(v>=0)&(u+v<=1)
 best=np.where(inside,face,np.inf)
 for x,y in [(a,b),(b,c),(c,a)]:
  e=y-x;q=point-x;norm=np.einsum('...i,...i->...',e,e);t=np.einsum('...i,...i->...',q,e)/np.maximum(norm,np.finfo(float).tiny);t=np.clip(t,0,1)
  delta=q-t[...,None]*e;best=np.minimum(best,np.einsum('...i,...i->...',delta,delta))
 return best

class TriangleDistance:
 def __init__(self,triangles):
  self.triangles=np.asarray(triangles);self.centroids=self.triangles.mean(1);self.radius=np.linalg.norm(self.triangles-self.centroids[:,None,:],axis=2).max(1);self.max_radius=float(self.radius.max());self.tree=cKDTree(self.centroids)
 def query(self,points,batch=128,return_indices=False):
  answer=np.empty(len(points));nearest=np.empty(len(points),dtype=int);max_k=0;expansions=0;n=len(self.triangles)
  for lo in range(0,len(points),batch):
   block=np.asarray(points[lo:lo+batch]);active=np.arange(len(block));k=min(32,n)
   while len(active):
    d,ids=self.tree.query(block[active],k=k,workers=1)
    if k==1:d=d[:,None];ids=ids[:,None]
    ds=squared_distance(block[active,None,:],self.triangles[ids]);which=ds.argmin(1)
    exact=np.sqrt(ds[np.arange(len(active)),which]);max_k=max(max_k,k)
    # Every unseen triangle has centroid distance >= d_k and bounding radius <= R_max.
    # Thus its point-to-triangle distance is >= d_k - R_max.
    done=np.ones(len(active),bool) if k==n else (d[:,-1]-self.max_radius>=exact+1e-12)
    answer[lo+active[done]]=exact[done];nearest[lo+active[done]]=ids[np.arange(len(active))[done],which[done]];active=active[~done]
    if len(active):k=min(n,2*k);expansions+=len(active)
  diagnostics=dict(initial_k=32,maximum_k=max_k,triangle_count=n,global_centroid_bounding_radius_m=self.max_radius,candidate_expansions=expansions)
  return (answer,nearest,diagnostics) if return_indices else (answer,diagnostics)
