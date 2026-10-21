"""Replay the archived Guide input through RoboTwin SDF and query its cooked field."""
import argparse
import json
from pathlib import Path
import numpy as np
import sapien
import sapien.physx as physx
import torch
import sapien_sdf_bridge as bridge
from isolated_gpu import enable_gpu
from tests.acceptance.cases import load_suite
from tests.acceptance.runner import ball_force
import xbox_gamepad_physics.resources as resources
from xbox_gamepad_physics.robotwin import load_into_scene

p=argparse.ArgumentParser();p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--inputs',type=Path,required=True)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
resources.resource_root=lambda:a.resources
inputs=json.loads((a.inputs/'targets.json').read_text())
world=np.load(a.inputs/'sample_points.npz')['world_m'].reshape(-1,3)
suite=load_suite();case=suite.case('Guide');dt=inputs['dt_s'];settings=suite.settings
assert np.allclose(physx.get_scene_config().gravity,suite.fixture['gravity_m_s2'])
system=physx.PhysxCpuSystem();scene=sapien.Scene([system]);scene.set_timestep(dt)
pad=load_into_scene(scene,pose=inputs['root_pose'],fixed_root=True,attach_visual=False,collision='sdf')
links={link.name:link for link in pad.articulation.get_links()}
# The independent GPU scene shares the already cooked CPU mesh. Its static
# bodies cannot change the CPU dynamics, articulation or contact filtering.
enable_gpu();query_system=physx.PhysxGpuSystem('cuda:0');query_scene=sapien.Scene([query_system])
query_shapes=[];metadata=[]
for name in ['controller_body','guide']:
    link=links[name]
    for index,source in enumerate(link.get_collision_shapes()):
        assert isinstance(source,physx.PhysxCollisionShapeTriangleMesh),type(source)
        entity=sapien.Entity();body=physx.PhysxRigidStaticComponent();entity.add_component(body)
        bridge.attach_shared_clone(source,body);query_scene.add_entity(entity)
        clone=body.get_collision_shapes()[0]
        assert bridge.same_cooked_mesh(source,clone),'query must use original cooked SDF'
        transform=link.pose*source.local_pose
        info=bridge.shape_info(source)
        info.update(link=name,shape_index=index,same_cooked_mesh=True,world_pose=[*transform.p.tolist(),*transform.q.tolist()],
                    scale=np.asarray(source.scale).tolist(),contact_offset_m=float(source.contact_offset),rest_offset_m=float(source.rest_offset))
        assert np.allclose(source.scale,[1,1,1]),'query local mesh coordinates require unit scale'
        metadata.append(info);query_shapes.append((clone,transform))
query_system.gpu_init();query_scene.step()
fields=[]
for (shape,transform),info in zip(query_shapes,metadata):
    inv=transform.inv();matrix=inv.to_transformation_matrix()
    local=world@matrix[:3,:3].T+matrix[:3,3]
    points=torch.zeros((len(world),4),dtype=torch.float32,device='cuda:0');points[:,:3]=torch.as_tensor(local,device='cuda:0')
    shape_id=bridge.shape_info(shape)['internal_shape_id'];assert shape_id!=4294967295
    ids=torch.tensor([shape_id],dtype=torch.int32,device='cuda:0')
    counts=torch.tensor([len(world)],dtype=torch.int32,device='cuda:0');out=torch.empty_like(points)
    bridge.sample(query_system,ids.data_ptr(),points.data_ptr(),counts.data_ptr(),len(world),out.data_ptr());torch.cuda.synchronize()
    values=out.cpu().numpy();assert np.isfinite(values).all()
    fields.append(values)
np.savez_compressed(a.output/'cooked_sdf.npz',world_m=world,gradient_xyz_distance_w=np.asarray(fields),links=np.asarray([r['link'] for r in metadata]))
(a.output/'field_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
# Same frozen dynamic probe as teleop BallProbe and the shared PressExecutor.
builder=scene.create_actor_builder();mat=scene.create_physical_material(.8,.6,0)
builder.add_sphere_collision(radius=settings['radius_m'],material=mat)
builder.set_mass_and_inertia(settings['mass_kg'],sapien.Pose(),[2*settings['mass_kg']*settings['radius_m']**2/5]*3)
probe_entity=builder.build(name='probe')
probe=probe_entity.find_component_by_type(physx.PhysxRigidDynamicComponent)
for shape in probe.get_collision_shapes():
    shape.set_collision_groups([1,1,0,0]);shape.set_contact_offset(.0002);shape.set_rest_offset(0)
start=np.asarray(case.plan['start_m']);direction=np.asarray(case.plan['direction'])
probe_entity.set_pose(sapien.Pose(start-direction*.015));probe.set_linear_velocity([0,0,0]);probe.set_angular_velocity([0,0,0])
with (a.output/'trajectory.jsonl').open('w') as output:
    for target in inputs['sequence']:
        force=ball_force(settings,target['target_m'],probe.pose.p,probe.linear_velocity,suite.fixture['gravity_m_s2'])
        probe.add_force_at_point(force,probe.pose.p);scene.step()
        contacts=[]
        for contact in scene.get_contacts():
            names=[contact.bodies[0].entity.name,contact.bodies[1].entity.name]
            if 'probe' not in names:continue
            other=names[1-names.index('probe')]
            if other not in ['controller_body','guide']:continue
            for point in contact.points:
                contacts.append({'link':other,'bodies':names,'point_m':point.position.tolist(),'normal':point.normal.tolist(),
                                 'separation_m':float(point.separation),'impulse_ns':point.impulse.tolist()})
        row={**target,'actual_s_m':float(np.dot(probe.pose.p-start,direction)),
             'q_m':pad.joint_positions()['guide_press'],'probe_position_m':probe.pose.p.tolist(),
             'force_n':list(force),'contacts':contacts}
        output.write(json.dumps(row)+'\n')
(a.output/'result.json').write_text(json.dumps({'status':'completed','steps':len(inputs['sequence']),
 'sdf_source':'RoboTwin SDF loader; original CPU cooked mesh shared into separate GPU query scene',
 'physics_system':'PhysxCpuSystem','query_system':'PhysxGpuSystem on configured visible CUDA device',
 'physics_version':bridge.shape_info(query_shapes[0][0])['header_physx_version'],
 'solver_iterations':None,'solver_iterations_reason':'not exposed per articulation link in this binding; native settings unchanged',
 'sample_count_per_shape':len(world),'cuda_device':torch.cuda.get_device_name(0)},indent=2)+'\n')
print('SAPIEN_GUIDE_COMPLETED',flush=True)
