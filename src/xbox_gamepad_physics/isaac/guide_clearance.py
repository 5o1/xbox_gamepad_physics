"""Neutral Guide ray and swept-sphere clearance against native SDF and source triangles."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np


class SdfShapeCollection:
    """Bind explicit SDF paths on Sim 5.1's single-string native pattern API."""
    def __init__(self,paths,num_points):
        import omni.physics.tensors as tensors
        self.simulation_view=tensors.create_simulation_view('torch')
        self.simulation_view.set_subspace_roots('/')
        self.views=[self.simulation_view.create_sdf_shape_view(str(path),num_points) for path in paths]
        if any(view.count!=1 for view in self.views):
            raise RuntimeError('an explicit cooked SDF shape path is missing or ambiguous')
        self.object_paths=[str(view.object_paths[0]) for view in self.views]
        self.count=len(self.views)
    def get_sdf_and_gradients(self,points):
        import torch
        return torch.cat([view.get_sdf_and_gradients(points[i:i+1]) for i,view in enumerate(self.views)],dim=0)


def _ray_hits(origin,direction,triangles):
    a=triangles[:,0];e1=triangles[:,1]-a;e2=triangles[:,2]-a
    h=np.cross(np.broadcast_to(direction,e2.shape),e2);det=np.einsum('ij,ij->i',e1,h)
    valid=np.abs(det)>1e-15;inv=np.divide(1.,det,out=np.zeros_like(det),where=valid)
    s=origin-a;u=inv*np.einsum('ij,ij->i',s,h);q=np.cross(s,e1)
    v=inv*(q@direction);t=inv*np.einsum('ij,ij->i',e2,q)
    hits=np.sort(t[valid&(u>=-1e-10)&(v>=-1e-10)&(u+v<=1+1e-10)&(t>=0)])
    return hits[np.r_[True,np.diff(hits)>1e-8]] if len(hits) else hits


def _point_distances(points,triangles):
    a=triangles[:,0];ab=triangles[:,1]-a;ac=triangles[:,2]-a
    normal=np.cross(ab,ac);norm2=np.einsum('ij,ij->i',normal,normal)
    ab2=np.einsum('ij,ij->i',ab,ab);ac2=np.einsum('ij,ij->i',ac,ac);abac=np.einsum('ij,ij->i',ab,ac)
    den=ab2*ac2-abac*abac
    out=[]
    for chunk in np.array_split(points,max(1,int(np.ceil(len(points)/64)))):
        ap=chunk[:,None,:]-a[None,:,:]
        d=np.einsum('pmk,mk->pm',ap,normal)
        plane2=np.divide(d*d,norm2[None,:],out=np.full(d.shape,np.inf),where=norm2[None,:]>1e-30)
        d1=np.einsum('pmk,mk->pm',ap,ab);d2=np.einsum('pmk,mk->pm',ap,ac)
        u=np.divide(ac2*d1-abac*d2,den[None,:],out=np.zeros_like(d1),where=den[None,:]>1e-30)
        v=np.divide(ab2*d2-abac*d1,den[None,:],out=np.zeros_like(d2),where=den[None,:]>1e-30)
        inside=(u>=0)&(v>=0)&(u+v<=1)&(den[None,:]>1e-30)
        best=np.where(inside,plane2,np.inf)
        for p0,p1 in ((triangles[:,0],triangles[:,1]),(triangles[:,1],triangles[:,2]),(triangles[:,2],triangles[:,0])):
            edge=p1-p0;diff=chunk[:,None,:]-p0[None,:,:]
            t=(np.einsum('pmk,mk->pm',diff,edge)/np.maximum(np.einsum('ij,ij->i',edge,edge),1e-30)).clip(0,1)
            residual=diff-t[:,:,None]*edge
            best=np.minimum(best,np.einsum('pmk,pmk->pm',residual,residual))
        out.extend(np.sqrt(best.min(1)).tolist())
    return np.asarray(out)


def _crossing(t,values,level):
    valid=np.where(values<=level)[0]
    if not len(valid):return None
    k=int(valid[0])
    if not k:return float(t[0])
    a,b=values[k-1],values[k]
    return float(t[k-1]+(t[k]-t[k-1])*(a-level)/(a-b)) if a!=b else float(t[k])


def measure_guide_clearance(stage,sdf,*,collisions,case,radius_m,device,reference_path=None):
    import torch
    import omni.physics.tensors as tensors
    from pxr import UsdGeom,Gf
    from ..backends.common.collision import _objects
    origin=np.asarray(case.plan['start_m'],dtype=np.float64)
    direction=np.asarray(case.plan['direction'],dtype=np.float64);direction/=np.linalg.norm(direction)
    t=np.linspace(0.,.02,4097);world=origin[None,:]+t[:,None]*direction
    reference_path=Path(reference_path) if reference_path is not None else None
    if reference_path is not None and reference_path.is_file():
        reference=json.loads(reference_path.read_text())
        if reference['origin_m']!=origin.tolist() or reference['direction_unit']!=direction.tolist():
            raise ValueError('neutral reference ray differs')
        triangle_curves={k:np.asarray(v) for k,v in reference['triangle_signed_distance_m'].items()}
    else:
        groups={'shell':[],'guide':[]};rays={'shell':[],'guide':[]}
        for source in collisions:
            group='shell' if source.component in {'shell','shell_front_plate'} else 'guide' if source.component=='guide' else None
            if group is None:continue
            for path in source.triangle_shells:
                for _,vertices,faces in _objects(source.root/path):
                    # These common triangle_shells use the simulation frame;
                    # this frozen case has identity root orientation.
                    if tuple(case.root_pose.orientation_wxyz)!=(1.,0.,0.,0.):raise ValueError('reference expects frozen identity root')
                    tri=np.asarray(vertices)[np.asarray(faces)]+np.asarray(case.root_pose.position_m)
                    hits=_ray_hits(origin,direction,tri);rays[group].extend(hits.tolist())
                    distance=_point_distances(world,tri)
                    inside=(np.searchsorted(hits,t,side='right')%2)==1
                    groups[group].append(np.where(inside,-distance,distance))
        triangle_curves={k:np.min(np.asarray(v),axis=0) for k,v in groups.items()}
        reference={'origin_m':origin.tolist(),'direction_unit':direction.tolist(),'travel_m':t.tolist(),
            'triangle_signed_distance_m':{k:v.tolist() for k,v in triangle_curves.items()},
            'triangle_axial_first_hit_m':{k:min(v) if v else None for k,v in rays.items()},
            'reference':'same triangle_shells used by SAPIEN; geometric reference, not SAPIEN cooked-SDF readback'}
        if reference_path is not None:
            reference_path.parent.mkdir(parents=True,exist_ok=True)
            reference_path.write_text(json.dumps(reference)+'\n')
    native_curves={};native_paths={}
    if sdf is not None:
        paths=[p for p in sdf.object_paths if '/controller_body/' in p or '/guide/' in p]
        if paths:
            native=SdfShapeCollection(paths,4097)
            local=[];groups=[];xf=UsdGeom.XformCache()
            for path in native.object_paths:
                inv=xf.GetLocalToWorldTransform(stage.GetPrimAtPath(path)).GetInverse()
                local.append([tuple(inv.Transform(Gf.Vec3d(*point))) for point in world])
                groups.append('shell' if '/controller_body/' in path else 'guide')
            data=native.get_sdf_and_gradients(torch.tensor(np.asarray(local,dtype=np.float32),device=device)).cpu().numpy()[:,:,-1]
            if not np.isfinite(data).all():raise RuntimeError('neutral SDF query returned nonfinite samples')
            for group in ['shell','guide']:
                indices=[i for i,g in enumerate(groups) if g==group]
                if indices:
                    native_curves[group]=np.min(data[indices],axis=0)
                    native_paths[group]=[native.object_paths[i] for i in indices]
    result={'neutral_joint_q':'initial_position from common physical; no step before query','origin_m':origin.tolist(),
        'direction_unit':direction.tolist(),'sphere_radius_m':radius_m,'sample_pitch_m':float(t[1]-t[0]),
        'reference':reference['reference'],'triangle_axial_first_hit_m':reference['triangle_axial_first_hit_m'],
        'travel_m':t.tolist(),'groups':{},'native_paths':native_paths}
    for group in ['shell','guide']:
        a=triangle_curves[group];b=native_curves.get(group)
        result['groups'][group]={'triangle_distance_at_origin_m':float(a[0]),'triangle_sphere_first_touch_travel_m':_crossing(t,a,radius_m),
            'native_sdf_distance_at_origin_m':float(b[0]) if b is not None else None,
            'native_sdf_sphere_first_touch_travel_m':_crossing(t,b,radius_m) if b is not None else None,
            'native_sdf_axial_first_zero_m':_crossing(t,b,0.) if b is not None else None,
            'native_sdf_distance_m':b.tolist() if b is not None else None,
            'triangle_signed_distance_m':a.tolist(),
            'missing_reason':None if b is not None else 'Group uses CoACD; no cooked SDF query exists'}
    return result
