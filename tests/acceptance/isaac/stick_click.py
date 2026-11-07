"""Native Isaac execution of the frozen stick-click protocol; launch after AppLauncher.

The shared protocol is read unchanged. Each process runs one bounded condition.
All execution and scoring lives here; callers select independent conditions.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def main():
    from isaaclab.app import AppLauncher
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resources',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--protocol',type=Path,required=True)
    p.add_argument('--test',choices=['readback','T1','T2','T3','T3P','T4'],required=True)
    p.add_argument('--root-mode',choices=['fixed','free'],default='fixed')
    p.add_argument('--side',choices=['left','right'],default='left')
    p.add_argument('--angle',type=float,default=0.)
    p.add_argument('--multiplier',type=float,default=.5)
    p.add_argument('--normal-force',type=float,default=1.)
    p.add_argument('--case-id')
    p.add_argument('--baseline-resources',type=Path)
    p.add_argument('--baseline-source',type=Path)
    AppLauncher.add_app_launcher_args(p)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    P=json.loads(a.protocol.read_text());dt=P['dt_s']
    result={'test':a.test,'status':'starting','passed':None,
        'protocol_id':P['protocol_id'],'protocol_sha256':hashlib.sha256(a.protocol.read_bytes()).hexdigest(),
        'dt_s':dt,'side':a.side,'angle_deg':a.angle,'root_mode':a.root_mode,
        'baseline':a.baseline_resources is not None}
    save(a.output/'result.json',result)
    app=AppLauncher(a).app
    try:
        import importlib.metadata
        import sys
        import xbox_gamepad_physics
        result['package_file']=str(Path(xbox_gamepad_physics.__file__).resolve())
        try:
            result['package_version']=importlib.metadata.version('xbox-gamepad-physics')
        except importlib.metadata.PackageNotFoundError:
            result['package_version']=None  # Source runs can lack installed metadata.
        result['python_executable']=sys.executable
        import numpy as np
        import torch
        import omni.usd
        from pxr import UsdGeom,UsdPhysics,PhysxSchema
        import isaaclab.sim as su
        from isaaclab.sim import SimulationCfg,SimulationContext
        from isaaclab.assets import Articulation,RigidObject,RigidObjectCfg
        from isaaclab.sensors import ContactSensor,ContactSensorCfg
        from xbox_gamepad_physics.motion import motion_from_dict
        from xbox_gamepad_physics.backends.common.appearance import load_appearance,bind_appearance_to_motion
        from xbox_gamepad_physics.backends.common.physical import load_physical
        from xbox_gamepad_physics.backends.common.collision import load_collision_sources
        from xbox_gamepad_physics.backends.common.model import Evidence,Parameter
        from xbox_gamepad_physics.isaac import build_usd,make_articulation_cfg,bind_articulation
        from xbox_gamepad_physics.isaac.shaft_limits import _rotate
        from tests.acceptance.isaac.readback import readback_usd,readback_articulation
        from tests.acceptance.isaac.executor import IsaacPressExecutor
        from tests.acceptance.cases import load_suite
        from tests.acceptance.records import ResultSink
        suite=load_suite();root_pose=suite.cases[0].root_pose
        resources=a.baseline_resources or a.resources
        c=resources/'common/xbox_one_s'
        motion=motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()))
        physical=load_physical(resource_directory=c/'physical')
        if a.baseline_resources:
            if a.baseline_source is None:raise ValueError('baseline requires the archived 73c8676 source directory')
            import importlib.util
            def old_module(name):
                path=a.baseline_source/'src/xbox_gamepad_physics/isaac'/f'{name}.py'
                spec=importlib.util.spec_from_file_location(f'xbox_gamepad_physics.isaac._old_{name}',path)
                module=importlib.util.module_from_spec(spec)
                import sys
                sys.modules[spec.name]=module;spec.loader.exec_module(module)
                return module
            build_usd=old_module('builder').build_usd
            old_articulation=old_module('articulation')
            make_articulation_cfg=old_articulation.make_articulation_cfg
            bind_articulation=old_articulation.bind_articulation
            result['baseline_commit']='73c867636804ef80217c54564bcee01c18c7c695'
            result['baseline_native_implementation']='original builder, cfg and handle; original force-drive target; zero added effort'
        appearance=bind_appearance_to_motion(load_appearance(directory=c/'visual'),
            json.loads((resources/'kinematics/xbox_one_s.json').read_text()),motion)
        collisions=load_collision_sources(directory=c/'collision')
        proof=Evidence('tests/acceptance/data/ruling20_sdf303_v1.json','fixture.sapien_mapping',
            'Frozen contact/rest offsets mapped to native PhysX.','Identical SI length values.',category='fixture_definition')
        offsets={k:Parameter(suite.fixture['sapien_mapping'][k],'m',(proof,)) for k in ['contact_offset_m','rest_offset_m']}
        artifact=build_usd(a.output/'controller.usda',motion=motion,physical=physical,appearance=appearance,
            collision_sources=collisions,visual_directory=c/'visual',root_mode=a.root_mode,contact_offsets=offsets)
        usd=artifact.usd_path
        if not a.baseline_resources:result['usd']=readback_usd(artifact,motion=motion,physical=physical,appearance=appearance,collision_sources=collisions)
        result['abxy_upper_m']={n:motion.joint_by_name[n+'_press'].upper for n in 'abxy'}
        sim=SimulationContext(SimulationCfg(dt=dt,device=a.device,gravity=tuple(P['gravity_m_s2']),log_dir=str(a.output/'lab_logs')))
        cfg=make_articulation_cfg(usd,motion=motion,physical=physical,root_pose=root_pose,
                                  activate_contact_sensors=a.test in ['T3','T4'])
        # Exercise class_type initialization directly, with no binder for preload initialization.
        art=cfg.class_type(cfg)
        probe=None;sensors={}
        if a.test in ['T3','T4']:
            probe=RigidObject(RigidObjectCfg(prim_path='/World/Probe',spawn=su.SphereCfg(
                radius=suite.settings['radius_m'],mass_props=su.MassPropertiesCfg(mass=suite.settings['mass_kg']),
                rigid_props=su.RigidBodyPropertiesCfg(),collision_props=su.CollisionPropertiesCfg(contact_offset=.0002,rest_offset=0.),
                physics_material=su.RigidBodyMaterialCfg(**suite.fixture['sphere_material'])),
                init_state=RigidObjectCfg.InitialStateCfg(pos=(0.,0.,.3))))
            links=sorted({'controller_body'}|{x.plan['link'] for x in suite.cases})
            sensors={link:ContactSensor(ContactSensorCfg(prim_path='/World/Gamepad/Links/'+link,
                filter_prim_paths_expr=['/World/Probe'],track_contact_points=True,update_period=0.,max_contact_data_count_per_prim=256)) for link in links}
        sim.reset();art.update(dt)
        result['native']=readback_articulation(art,motion=motion,physical=physical)
        fields=['solver_type','min_position_iteration_count','max_position_iteration_count',
                'min_velocity_iteration_count','max_velocity_iteration_count','enable_external_forces_every_iteration']
        result['physx_configuration']={n:getattr(sim.cfg.physx,n) for n in fields}
        result['initial_effort_buffer_n']=art.data.joint_effort_target[0].cpu().tolist()
        result['joint_names']=list(art.joint_names)
        result['click_usd_drive_target_m']={side:UsdPhysics.DriveAPI(
            stage_prim,'linear').GetTargetPositionAttr().Get() for side in ['left','right']
            for stage_prim in [omni.usd.get_context().get_stage().GetPrimAtPath('/World/Gamepad/Joints/'+side+'_stick_click')]}
        stage=omni.usd.get_context().get_stage()
        native_api=PhysxSchema.PhysxArticulationAPI(stage.GetPrimAtPath('/World/Gamepad'))
        result['articulation_solver_iterations']={'position':native_api.GetSolverPositionIterationCountAttr().Get(),
            'velocity':native_api.GetSolverVelocityIterationCountAttr().Get()}
        pad=None if a.test=='readback' else bind_articulation(art,motion=motion,physical=physical)
        result['bound_click_effort_n']={side:float(art.root_physx_view.get_dof_actuation_forces()[0,art.joint_names.index(side+'_stick_click')]) for side in ['left','right']}
        def tick():
            art.write_data_to_sim()
            if probe:probe.write_data_to_sim()
            sim.step(render=False);art.update(dt)
            if probe:probe.update(dt)
            for sensor in sensors.values():sensor.update(dt,force_recompute=True)
        if a.test=='readback':
            click_ids=[art.joint_names.index(side+'_stick_click') for side in ['left','right']]
            def snapshot(label):
                return {'phase':label,'buffer_n':art.data.joint_effort_target[0,click_ids].cpu().tolist(),
                    'native_actuation_n':art.root_physx_view.get_dof_actuation_forces()[0,click_ids].cpu().tolist(),
                    'native_projected_joint_n':art.root_physx_view.get_dof_projected_joint_forces()[0,click_ids].cpu().tolist(),
                    'q_m':art.root_physx_view.get_dof_positions()[0,click_ids].cpu().tolist()}
            life=[snapshot('initialized_before_bind')]
            for _ in range(25):tick()
            life.append(snapshot('25_regular_write_steps_before_bind'))
            art.reset();life.append(snapshot('asset_reset_before_bind'))
            for _ in range(25):tick()
            life.append(snapshot('25_regular_write_steps_after_reset_before_bind'))
            result['automatic_preload_lifecycle']=life
            result['automatic_preload_preserved']=all(abs(v+7.4)<1e-5 for r in life for k in ['buffer_n','native_actuation_n'] for v in r[k])
            override=art.root_physx_view.get_dof_actuation_forces().clone();override[:,click_ids]=0.
            art.root_physx_view.set_dof_actuation_forces(override,torch.tensor([0],device=art.device,dtype=torch.int64))
            control=[snapshot('native_effort_only_overwritten_to_zero')]
            art.write_data_to_sim();control.append(snapshot('lab_write_restores_persistent_buffer'))
            result['native_override_control']=control
            pad=bind_articulation(art,motion=motion,physical=physical)
            initial=art.data.root_pos_w.clone()
            if a.root_mode=='free':
                v=torch.zeros((1,6),device=art.device);v[:,0]=.01;art.write_root_velocity_to_sim(v)
            for _ in range(25):tick()
            result['final_effort_buffer_n']=art.data.joint_effort_target[0].cpu().tolist()
            result['root_delta_m']=(art.data.root_pos_w-initial)[0].cpu().tolist()
            result['root_fixed']=bool(art.is_fixed_base)
            result['signals']=pad.gamepad_state().as_dict()
            result['passed']=result['automatic_preload_preserved'] and bool(art.is_fixed_base)==(a.root_mode=='fixed') and (a.root_mode=='fixed' or result['root_delta_m'][0]>.0001)
        elif a.test=='T3P':
            from tests.acceptance.isaac.t3_point import force_schedule,score_point
            from xbox_gamepad_physics.isaac.guide_clearance import SdfShapeCollection
            if a.normal_force not in P['vertical_forces_n']:raise ValueError('unregistered T3-v2 vertical force')
            side=a.side;cap=art.body_names.index(side+'_stick');shell=art.body_names.index('controller_body')
            stage=omni.usd.get_context().get_stage()
            paths=[str(prim.GetPath()) for prim in stage.Traverse()
                if '/World/Gamepad/Links/'+side+'_stick/Collision/' in str(prim.GetPath()) and prim.IsA(UsdGeom.Mesh)]
            groups=[np.asarray(UsdGeom.Mesh(stage.GetPrimAtPath(path)).GetPointsAttr().Get(),dtype=float) for path in paths]
            upper=max(groups,key=lambda points:points[:,2].max())
            lower_bound=upper.min(0);upper_bound=upper.max(0)
            center=(lower_bound+upper_bound)/2
            radius=float(((upper_bound-lower_bound)[:2]/2).mean())
            direction=P['sides'][side]['shell_horizontal_axis']
            from xbox_gamepad_physics.backends.common.transforms import neutral_link_poses,rotate
            neutral=neutral_link_poses(motion)
            cap_q=neutral[side+'_stick'].orientation_wxyz
            inverse=(cap_q[0],-cap_q[1],-cap_q[2],-cap_q[3])
            local_direction=rotate(inverse,rotate(neutral['controller_body'].orientation_wxyz,tuple(direction)))
            result['neutral_push_direction_in_stick_local']=local_direction
            point=center.copy();point[:2]+=P['point']['radius_fraction']*radius*np.asarray(local_direction[:2])
            z=np.linspace(upper_bound[2]+radius,lower_bound[2]-radius,4097)
            queries=np.tile(point,(len(z),1));queries[:,2]=z
            sdf=SdfShapeCollection(paths,len(z))
            native=sdf.get_sdf_and_gradients(torch.tensor(queries,dtype=torch.float32,device=art.device)[None].expand(len(paths),-1,-1).contiguous())
            distance=native[:,:,-1].min(0).values.cpu().numpy()
            hits=np.flatnonzero(distance<=0)
            if not len(hits) or hits[0]==0:raise RuntimeError('native cap top ray has no outside-to-inside zero crossing')
            k=int(hits[0]);fraction=distance[k-1]/(distance[k-1]-distance[k])
            point[2]=z[k-1]+fraction*(z[k]-z[k-1])
            point_local=torch.tensor(point[None],device=art.device,dtype=torch.float32)
            result.update(point_local_m=point.tolist(),cap_radius_m=radius,cap_center_local_m=center.tolist(),
                cap_bounds_local_m=[lower_bound.tolist(),upper_bound.tolist()],point_surface_method='upper cap radius and center from highest collision component; topmost native cooked SDF zero crossing',
                vertical_force_n=a.normal_force,horizontal_force_n=P['horizontal_force_n'],shell_horizontal_axis=direction,
                sphere_present=False,source_usd=str(artifact.usd_path))
            env_ids=torch.tensor([0],device=art.device,dtype=torch.int32)
            x_axis=torch.tensor([direction],device=art.device,dtype=torch.float32)
            z_axis=torch.tensor([P['shell_vertical_axis']],device=art.device,dtype=torch.float32)
            click=art.joint_names.index(side+'_stick_click');rows=[]
            with (a.output/'trace.jsonl').open('w') as sink:
                for spec in force_schedule(P):
                    shell_q=art.data.body_link_quat_w[:,shell]
                    horizontal=_rotate(shell_q,x_axis)[0]*P['horizontal_force_n']*spec['gain']
                    vertical=_rotate(shell_q,z_axis)[0]*a.normal_force*spec['gain']
                    application=art.data.body_link_pos_w[:,cap]+_rotate(art.data.body_link_quat_w[:,cap],point_local)
                    forces=torch.zeros((1,art.num_bodies,3),device=art.device);torques=torch.zeros_like(forces)
                    positions=art.data.body_link_pos_w.clone();forces[:,cap]=horizontal+vertical;positions[:,cap]=application
                    art.write_data_to_sim()
                    art.root_physx_view.apply_forces_and_torques_at_position(forces,torques,positions,env_ids,True)
                    sim.step(render=False);art.update(dt)
                    shaft=_rotate(art.data.body_link_quat_w[:,cap],z_axis)[0]
                    inward=_rotate(art.data.body_link_quat_w[:,shell],z_axis)[0]
                    cosine=float(torch.dot(shaft,inward).clamp(-1.,1.));q=float(art.data.joint_pos[0,click])
                    bodies=torch.cat((art.data.body_link_pos_w[0],art.data.body_link_quat_w[0]),-1).cpu().tolist()
                    row={**spec,'q_m':q,'raw_fraction':q/P['travel_m'],
                        'signal':pad.gamepad_state().channel(side+'_stick'),'shaft_angle_deg':math.degrees(math.acos(cosine)),
                        'application_point_world_m':application[0].cpu().tolist(),
                        'force_horizontal_world_n':horizontal.cpu().tolist(),'force_vertical_world_n':vertical.cpu().tolist(),
                        'body_poses':dict(zip(art.body_names,bodies))}
                    rows.append(row);sink.write(json.dumps(row)+'\n')
            result.update(score_point(rows,P,a.normal_force))
            result['raw_q_range_m']=[min(r['q_m'] for r in rows),max(r['q_m'] for r in rows)]
        elif a.test in ['T1','T2','T3']:
            side=a.side;cap=art.body_names.index(side+'_stick');shell=art.body_names.index('controller_body')
            axis=torch.tensor([[0.,0.,-1.]],device=art.device)
            inward=_rotate(art.data.body_link_quat_w[:,shell],axis)[0]
            # Actual collision vertices in the neutral native link frame define the cap center.
            stage=omni.usd.get_context().get_stage()
            vertices=[]
            for prim in stage.Traverse():
                if '/World/Gamepad/Links/'+side+'_stick/Collision/' in str(prim.GetPath()) and prim.IsA(UsdGeom.Mesh):
                    vertices.extend(UsdGeom.Mesh(prim).GetPointsAttr().Get())
            vertices=np.asarray(vertices);center=torch.tensor((vertices.min(0)+vertices.max(0))/2,device=art.device,dtype=torch.float32)[None]
            if a.test in ['T1','T2']:
                ids=[art.joint_names.index(side+'_stick_'+x) for x in ['x','y']]
                art.write_joint_stiffness_to_sim(torch.tensor([[100.,100.]],device=art.device),joint_ids=ids)
                art.write_joint_damping_to_sim(torch.tensor([[1.,1.]],device=art.device),joint_ids=ids)
                art.write_joint_effort_limit_to_sim(torch.tensor([[10.,10.]],device=art.device),joint_ids=ids)
                art.set_joint_position_target(torch.tensor([[math.radians(a.angle),0.]],device=art.device),joint_ids=ids)
            for _ in range(round(P['settle_s']/dt)):tick()
            click=art.joint_names.index(side+'_stick_click')
            def sample():
                direction=_rotate(art.data.body_link_quat_w[:,cap],axis)[0]
                cosine=float(torch.dot(direction,inward).clamp(-1.,1.))
                q=float(art.data.joint_pos[0,click]);signal=pad.gamepad_state().channel(side+'_stick')
                return {'q_m':q,'raw_fraction':q/P['travel_m'],'signal':signal,'cosine':cosine,
                        'shaft_angle_deg':math.degrees(math.acos(cosine))}
            def axial(force):
                direction=_rotate(art.data.body_link_quat_w[:,cap],axis)[0]
                point=art.data.body_link_pos_w[:,cap]+_rotate(art.data.body_link_quat_w[:,cap],center)
                forces=torch.zeros((1,art.num_bodies,3),device=art.device);torques=torch.zeros_like(forces)
                positions=art.data.body_link_pos_w.clone();forces[:,cap]=force*direction;positions[:,cap]=point
                art.write_data_to_sim()
                art.root_physx_view.apply_forces_and_torques_at_position(forces,torques,positions,
                    torch.tensor([0],device=art.device,dtype=torch.int32),True)
                sim.step(render=False);art.update(dt)
                return {**sample(),'applied_force_n':force,'force_vector_n':(force*direction).cpu().tolist(),'application_point_m':point[0].cpu().tolist()}
            rows=[]
            with (a.output/'trace.jsonl').open('w') as sink:
                if a.test=='T1':
                    steps=round(P['T1']['ramp_up_s']/dt)
                    for i in range(2*steps+1):
                        f=12*(i/steps if i<=steps else (2*steps-i)/steps)
                        row={**axial(f),'time_s':(i+1)*dt,'loading':i<=steps};rows.append(row);sink.write(json.dumps(row)+'\n')
                    loading=[r for r in rows if r['loading']]
                    def crossing(level):return next((r['applied_force_n'] for r in loading if r['signal']>=level),None)
                    f05,f50,f95=[crossing(v) for v in [.05,.5,.95]]
                    window=f95-f05 if f05 is not None and f95 is not None else None
                    trigger_row=next((r for r in loading if r['signal']>=.5),None)
                    expected=7.4/trigger_row['cosine'] if trigger_row is not None else 7.4/math.cos(math.radians(a.angle))
                    low=max(max(r['signal'],r['raw_fraction']) for r in rows if r['applied_force_n']<.9*7.4/r['cosine'])
                    error=max(abs(r['shaft_angle_deg']-a.angle) for r in rows)
                    passed=(low<=.05 and window is not None and window<=1 and f50 is not None and abs(f50/expected-1)<=.1
                        and max(rows[-1]['signal'],rows[-1]['raw_fraction'])<=.05 and error<=.5)
                    result.update(trigger_force_n=f50,predicted_force_n=expected,transition_window_n=window,
                        low_force_max_signal_or_fraction=low,max_angle_error_deg=error,final=rows[-1],passed=passed)
                elif a.test=='T2':
                    for i in range(round(P['T2']['hold_s']/dt)):
                        row={**axial(a.multiplier*7.4),'time_s':(i+1)*dt};rows.append(row);sink.write(json.dumps(row)+'\n')
                    stable=rows[-round(.5/dt):];low=max(max(r['signal'],r['raw_fraction']) for r in stable)
                    high=min(min(r['signal'],r['raw_fraction']) for r in stable)
                    middle=lambda r:sum(.05<x['signal']<.95 for x in r)/len(r)
                    result.update(multiplier=a.multiplier,stable_max=low,stable_min=high,middle_time_fraction=middle(rows),
                        stable_middle_time_fraction=middle(stable),passed=low<=.05 if a.multiplier<=.95 else high>=.95)
                else:
                    # Native filtered contact view gives impulse magnitudes, world normals and per-pair offsets.
                    plan=suite.case(side+'_x_pos').plan
                    tangent=torch.tensor(plan['direction'],device=art.device);tangent-=inward*torch.dot(tangent,inward);tangent/=tangent.norm()
                    # Locate the first sphere-tangent center on the frozen ray using the cooked native SDF.
                    from xbox_gamepad_physics.isaac.guide_clearance import SdfShapeCollection
                    paths=[str(prim.GetPath()) for prim in stage.Traverse() if '/World/Gamepad/Links/'+side+'_stick/Collision/' in str(prim.GetPath()) and prim.IsA(UsdGeom.Mesh)]
                    sdf=SdfShapeCollection(paths,4097)
                    ray=torch.tensor(plan['direction'],device=art.device)
                    ray_origin=torch.tensor(plan['point_m'],device=art.device)
                    original_ray_origin=ray_origin.clone()
                    world_vertices=art.data.body_link_pos_w[:,cap]+_rotate(art.data.body_link_quat_w[:,cap].expand(len(vertices),-1),torch.tensor(vertices,device=art.device,dtype=torch.float32))
                    outward=-inward
                    upper_center_height=(world_vertices@outward).max()+suite.settings['radius_m']-.0002
                    ray_origin+=outward*(upper_center_height-torch.dot(ray_origin,outward))
                    distance=torch.linspace(-.02,.01,4097,device=art.device)
                    world=ray_origin+distance[:,None]*ray
                    inverse=art.data.body_link_quat_w[:,cap].clone();inverse[:,1:]*=-1
                    local=_rotate(inverse.expand(len(world),-1),world-art.data.body_link_pos_w[:,cap])
                    data=sdf.get_sdf_and_gradients(local[None].expand(len(paths),-1,-1).contiguous())
                    values=data[:,:,-1].min(0).values-suite.settings['radius_m']
                    hits=torch.nonzero(values<=0).reshape(-1)
                    if not len(hits) or int(hits[0])==0:raise RuntimeError('frozen T3 ray has no outside-to-tangent cooked SDF crossing')
                    k=int(hits[0]);fraction=values[k-1]/(values[k-1]-values[k])
                    travel=distance[k-1]+fraction*(distance[k]-distance[k-1]);start=ray_origin+travel*ray
                    result['placement']={'cooked_sdf_paths':paths,'ray_sphere_tangent_m':float(travel),
                        'center_world_m':start.cpu().tolist(),'sample_pitch_m':.03/4096,
                        'original_ray_origin_m':original_ray_origin.cpu().tolist(),
                        'upper_side_ray_origin_m':ray_origin.cpu().tolist(),
                        'fixture_revision':'ruling1_upper_cap_planar_pd_v3',
                        'initial_sdf_gradient_local':data[int(data[:,k,-1].argmin()),k,:3].cpu().tolist(),
                        'method':'same frozen tangent and lateral section; height at cooked cap top + radius - native contact offset; first SDF distance=radius crossing'}
                    state=probe.data.default_root_state.clone();state[0,:3]=start;state[:,7:]=0;probe.write_root_state_to_sim(state);probe.reset();probe.update(dt)
                    sensor=sensors[side+'_stick']
                    groups=[torch.tensor(UsdGeom.Mesh(stage.GetPrimAtPath(path)).GetPointsAttr().Get(),device=art.device) for path in paths]
                    upper_group=max(groups,key=lambda points:float(points[:,2].max()))
                    upper_contact_local_z_min=float(upper_group[:,2].min())
                    result['placement']['upper_cap_region_local_z_min_m']=upper_contact_local_z_min
                    result['placement']['upper_cap_region_basis']='minimum local shaft-Z of the collision component with highest top; shared source geometry, no signal-based selection'
                    from tests.acceptance.isaac.t3_fixture import sphere_force
                    gradient=data[int(data[:,k,-1].argmin()),k,:3]
                    surface_normal=_rotate(art.data.body_link_quat_w[:,cap],gradient[None])[0]
                    surface_normal/=surface_normal.norm()
                    result['placement']['initial_sdf_normal_world']=surface_normal.cpu().tolist()
                    result['fixture_control']={'stiffness_n_m':suite.settings['stiffness_n_m'],'damping_ns_m':suite.settings['damping_ns_m'],
                        'horizontal_force_limit_n':suite.settings['force_limit_n'],'normal_position_feedback':False,
                        'horizontal_preload':'-Fn * sdf_normal_horizontal / sdf_normal_up; initial sloped-edge force balance'}
                    for i in range(round((P['T3']['push_s']+P['T3']['hold_s'])/dt)):
                        age=i*dt;target=start+tangent*min(.008,age*.005)
                        force=torch.tensor(sphere_force(target.cpu().tolist(),probe.data.root_pos_w[0].cpu().tolist(),
                            probe.data.root_lin_vel_w[0].cpu().tolist(),inward.cpu().tolist(),surface_normal.cpu().tolist(),
                            normal_force=a.normal_force,mass=suite.settings['mass_kg'],gravity=P['gravity_m_s2'],
                            stiffness=suite.settings['stiffness_n_m'],damping=suite.settings['damping_ns_m'],
                            horizontal_force_limit=suite.settings['force_limit_n']),device=art.device,dtype=torch.float32)
                        probe.permanent_wrench_composer.reset();probe.set_external_force_and_torque(force[None,None],torch.zeros((1,1,3),device=art.device),is_global=True)
                        tick()
                        magnitudes,points,normals,separations,counts,starts=sensor.contact_physx_view.get_contact_data(dt=dt)
                        count=int(counts.reshape(-1)[0]);offset=int(starts.reshape(-1)[0]);normal_vertical=0.;details=[]
                        for j in range(offset,offset+count):
                            normal=normals[j];magnitude=float(magnitudes[j].reshape(-1)[0]);component=abs(magnitude*float(torch.dot(normal,inward)))
                            normal_vertical+=component
                            cap_inverse=art.data.body_link_quat_w[:,cap].clone();cap_inverse[:,1:]*=-1
                            contact_local=_rotate(cap_inverse,(points[j]-art.data.body_link_pos_w[0,cap])[None])[0]
                            details.append({'point_cap_local_m':contact_local.cpu().tolist(),'upper_cap_region':float(contact_local[2])>=upper_contact_local_z_min,
                                'signed_inward_normal_force_n':magnitude*float(torch.dot(normal,inward)),'normal_world':normal.cpu().tolist(),'normal_force_n':magnitude,'vertical_normal_force_n':component,'point_world_m':points[j].cpu().tolist()})
                        frictions,friction_points,friction_counts,friction_starts=sensor.contact_physx_view.get_friction_data(dt=dt)
                        fc=int(friction_counts.reshape(-1)[0]);fs=int(friction_starts.reshape(-1)[0])
                        tangent_patches=[{'force_world_n':frictions[j].cpu().tolist(),'point_world_m':friction_points[j].cpu().tolist()} for j in range(fs,fs+fc)]
                        row={**sample(),'time_s':(i+1)*dt,'normal_vertical_contact_n':normal_vertical,'cap_contact_points':count,
                            'tangential_contact_patches':tangent_patches,
                            'probe_force_n':force.cpu().tolist(),'contacts':details,
                            'probe_position_m':probe.data.root_pos_w[0].cpu().tolist(),
                            'probe_velocity_m_s':probe.data.root_lin_vel_w[0].cpu().tolist(),
                            'pd_target_m':target.cpu().tolist(),
                            'native_cap_force_matrix_n':sensor.data.force_matrix_w.reshape(-1,3).sum(0).cpu().tolist(),
                            'cap_body_link_pose_m_wxyz':torch.cat((art.data.body_link_pos_w[0,cap],art.data.body_link_quat_w[0,cap])).cpu().tolist(),
                            'upper_cap_contact_points':sum(c['upper_cap_region'] and abs(c['normal_force_n'])>1e-6 for c in details),
                            'native_cap_net_force_n':sensor.data.net_forces_w.reshape(-1,3).sum(0).cpu().tolist(),
                            'all_link_force_matrix_n':{name:sen.data.force_matrix_w.reshape(-1,3).sum(0).cpu().tolist() for name,sen in sensors.items()}};rows.append(row);sink.write(json.dumps(row)+'\n')
                    scored=[r for r in rows if r['time_s']>.2 and r['cap_contact_points'] and r['normal_vertical_contact_n']<6.66]
                    maximum=max((max(r['signal'],r['raw_fraction']) for r in scored),default=None);tilt=max(r['shaft_angle_deg'] for r in rows)
                    result.update(normal_force_n=a.normal_force,scored_contact_steps=len(scored),max_signal_or_fraction_below_limit=maximum,
                        max_tilt_deg=tilt,passed=maximum is not None and maximum<=.05 and tilt>=1)
                    contact_rows=[r for r in rows if r['time_s']>.2 and r['upper_cap_contact_points'] and sum(f*f for f in r['native_cap_force_matrix_n'])>1e-12]
                    result['fixture_observable']=bool(scored) and tilt>=1
                    result['fixture_contact_samples_after_settle']=len(contact_rows)
                    result['fixture_contact_fraction_after_settle']=len(contact_rows)/sum(r['time_s']>.2 for r in rows)
                    result['fixture_contact_tail_samples']=sum(r['time_s']>=1.6 for r in contact_rows)
                    result['fixture_last_contact_s']=contact_rows[-1]['time_s'] if contact_rows else None
                    result['fixture_valid']=(result['fixture_observable'] and result['fixture_contact_fraction_after_settle']>=.95
                        and result['fixture_contact_tail_samples']>=.95*sum(r['time_s']>=1.6 for r in rows)
                        and result['fixture_last_contact_s']>=rows[-1]['time_s']-2*dt)
                    result['fixture_validation_policy']={'contact_fraction_min':.95,'tail_contact_fraction_min':.95,
                        'last_contact_max_age_s':2*dt,'basis':'Ruling 1 continuous upper-cap-region pushing, not whole-link/stem contact; frozen T3 signal criterion unchanged'}
            result['raw_q_range_m']=[min(r['q_m'] for r in rows),max(r['q_m'] for r in rows)]
        else:
            from tests.acceptance.runner import run_case
            e=IsaacPressExecutor(simulation=sim,gamepad=pad,probe=probe,sensors=sensors,root_pose=root_pose,
                                 radius_m=suite.settings['radius_m'],dt_s=dt)
            sink=ResultSink(a.output/'trace.jsonl')
            try:scored=run_case(e,suite,suite.case(a.case_id),sink)
            finally:sink.close()
            result.update(case=a.case_id,score=scored,passed=scored['physics_passed'])
        result['status']='passed' if result['passed'] else 'failed_physics'
        save(a.output/'result.json',result)
        print('CLICK_RESULT '+json.dumps({k:v for k,v in result.items() if k not in ['usd','native']}),flush=True)
        return int(not result['passed'])
    except BaseException as error:
        import traceback
        result.update(status='execution_error',error=type(error).__name__+': '+str(error))
        save(a.output/'result.json',result);(a.output/'failure.txt').write_text(traceback.format_exc());raise
    finally:app.close(skip_cleanup=True)


if __name__=='__main__':raise SystemExit(main())
