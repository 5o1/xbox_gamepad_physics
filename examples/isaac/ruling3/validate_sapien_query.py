"""Validate the temporary native bridge with an analytic cube on the selected GPU."""
import argparse
import json
from pathlib import Path
import numpy as np
import sapien
import sapien.physx as physx
import torch
import sapien_sdf_bridge as bridge
from isolated_gpu import enable_gpu

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
enable_gpu()
previous=physx.get_sdf_config()
physx.set_sdf_config(spacing=.001,subgrid_size=6,num_threads_for_construction=previous.num_threads_for_construction)
vertices=np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]],dtype=np.float32)*.01
faces=np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]],dtype=np.uint32)
source=physx.PhysxCollisionShapeTriangleMesh(vertices,faces,[1,1,1],physx.get_default_material(),sdf=True)
physx.set_sdf_config(previous)
system=physx.PhysxGpuSystem('cuda:0');scene=sapien.Scene([system])
entity=sapien.Entity();body=physx.PhysxRigidStaticComponent();entity.add_component(body)
bridge.attach_shared_clone(source,body);scene.add_entity(entity)
shape=body.get_collision_shapes()[0]
assert bridge.same_cooked_mesh(source,shape)
system.gpu_init();scene.step()
info=bridge.shape_info(shape);assert info['has_cooked_sdf'] and info['internal_shape_id']!=4294967295
points=torch.tensor([[0,0,0,0],[.012,0,0,0],[.01,0,0,0]],dtype=torch.float32,device='cuda:0')
ids=torch.tensor([info['internal_shape_id']],dtype=torch.int32,device='cuda:0')
counts=torch.tensor([len(points)],dtype=torch.int32,device='cuda:0');out=torch.empty_like(points)
bridge.sample(system,ids.data_ptr(),points.data_ptr(),counts.data_ptr(),len(points),out.data_ptr());torch.cuda.synchronize()
actual=out.cpu().numpy();expected=np.array([-.01,.002,0.])
error=float(np.max(np.abs(actual[:,3]-expected)))
result={'same_cooked_mesh':True,'native_info':info,'samples_xyz_m':points.cpu().numpy()[:,:3].tolist(),
 'gradient_xyz_distance_w':actual.tolist(),'expected_distances_m':expected.tolist(),'max_abs_error_m':error,
 'cuda_device':torch.cuda.get_device_name(0),'status':'passed' if error<.001 else 'failed'}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,indent=2)+'\n')
assert error<.001,result
print(json.dumps(result),flush=True)
