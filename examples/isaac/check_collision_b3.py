"""B3 native cook, actual SDF tensor and contact comparison fixture."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time
from isaaclab.app import AppLauncher
parser=argparse.ArgumentParser()
parser.add_argument('--resources',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--collision',choices=['sdf','coacd'],required=True)
parser.add_argument('--spacing-mm',type=float,choices=[.5,1.,2.],default=1.)
parser.add_argument('--cases',default='A,LT')
parser.add_argument('--full-suite',action='store_true')
parser.add_argument('--comparison-only',action='store_true')
parser.add_argument('--case-start',type=int,default=0)
parser.add_argument('--case-count',type=int)
parser.add_argument('--shell-spacing-mm',type=float,choices=[.5,1.,2.])
parser.add_argument('--shell-coacd',action='store_true')
parser.add_argument('--guide-coacd',action='store_true')
parser.add_argument('--contact-offset-mm',type=float,choices=[.1,.2],default=.2)
parser.add_argument('--measure-guide-clearance',action='store_true')
parser.add_argument('--diagnostic-no-shell-contact',action='store_true')
AppLauncher.add_app_launcher_args(parser)
args=parser.parse_args();launcher=AppLauncher(args);app=launcher.app

import numpy as np
import torch
import omni.usd
import omni.physx
import omni.physics.tensors as tensors
from pxr import Usd,UsdGeom,UsdPhysics,PhysxSchema,UsdUtils,PhysicsSchemaTools
import isaaclab.sim as sim_utils
from isaaclab.sim import SimulationContext,SimulationCfg
from isaaclab.assets import Articulation,RigidObject,RigidObjectCfg
from isaaclab.sensors import ContactSensor,ContactSensorCfg
from xbox_gamepad_physics.isaac import build_usd,make_articulation_cfg,bind_articulation
from xbox_gamepad_physics.isaac.press import IsaacPressExecutor
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.backends.common.appearance import load_appearance
from xbox_gamepad_physics.backends.common.collision import load_collision_sources
from xbox_gamepad_physics.backends.common.physical import load_physical
from xbox_gamepad_physics.backends.common.model import Evidence,Parameter
from xbox_gamepad_physics.acceptance.cases import load_suite
from xbox_gamepad_physics.acceptance.runner import run_case,ball_force
from xbox_gamepad_physics.acceptance.records import ResultSink

args.output.mkdir(parents=True,exist_ok=True)
result={'status':'running','collision':args.collision,'candidate_spacing_mm':args.spacing_mm if args.collision=='sdf' else None,
        'sdf_default':False,'cases':[]}
def save():
    (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
def gpu():
    return subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip()
def cooking():
    c=omni.physx.get_physx_cooking_private_interface().get_cooking_statistics()
    return {k:getattr(c,k) for k in ['total_scheduled_tasks','total_finished_tasks','total_finished_cache_hit_tasks',
        'total_finished_cache_miss_tasks','total_warnings_failed_gpu_compatibility','total_warnings_convex_polygon_limits_reached']}
r=args.resources;c=r/'common/xbox_one_s'
motion=motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()))
physical=load_physical(resource_directory=c/'physical')
appearance=load_appearance(directory=c/'visual',binding=json.loads((r/'review_binding.json').read_text()))
collisions=load_collision_sources(directory=c/'collision')
suite=load_suite();root_pose=suite.cases[0].root_pose
proof=Evidence('build_data/acceptance/ruling20_sdf303_v1.json','fixture.sapien_mapping',
 'Same frozen PhysX length-valued contact/rest offsets for the Isaac comparison fixture.',
 'Map the frozen 0.2 mm and zero metre offsets to native PhysxCollisionAPI attributes; no value fitting.',category='fixture_definition')
offsets={k:Parameter(suite.fixture['sapien_mapping'][k],'m',(proof,)) for k in ['contact_offset_m','rest_offset_m']}
if args.contact_offset_mm != .2:
    proof_offset=Evidence('Ruling 2', 'Guide diagnosis condition d',
        'One-factor 0.1 mm contact-offset control, not an adopted policy.',
        'Convert the user-requested millimetres to metres.',category='fixture_definition')
    offsets['contact_offset_m']=Parameter(args.contact_offset_mm*.001,'m',(proof_offset,))
options={'spacing_m':args.spacing_mm*.001,'subgrid_resolution':6,'bits_per_pixel':'BitsPerPixel16','margin':.01,'narrow_band_thickness':.02} if args.collision=='sdf' else None
overrides={}
for source in collisions:
    if source.component in {'shell','shell_front_plate'}:
        if args.shell_coacd:overrides[source.component]={'collision_mode':'coacd'}
        elif args.shell_spacing_mm is not None:
            overrides[source.component]={'collision_mode':'sdf','sdf_options':{**options,'spacing_m':args.shell_spacing_mm*.001}}
    if source.component=='guide' and args.guide_coacd:overrides[source.component]={'collision_mode':'coacd'}
result['diagnostic_overrides']=overrides
result['comparison_only']=args.comparison_only
result['fixture']={'suite':suite.suite_id,'sphere':suite.settings,'contact_offsets':{k:v.as_dict() for k,v in offsets.items()},
 'sdf_cook_controls':options,'sdf_controls_basis':'B0 explicit probe cook controls; candidate experiment, not calibrated defaults',
 'gravity_m_s2':suite.fixture['gravity_m_s2'],'dt_s':.004}
result['gpu_before']=gpu();result['cooking_before']=cooking()
artifact=build_usd(args.output/'controller.usda',motion=motion,physical=physical,appearance=appearance,
 collision_sources=collisions,visual_directory=c/'visual',root_mode='fixed',collision_mode=args.collision,
 sdf_options=options,contact_offsets=offsets,collision_overrides=overrides)
sim=SimulationContext(SimulationCfg(dt=.004,device=args.device,gravity=tuple(suite.fixture['gravity_m_s2']),log_dir=str(args.output/'lab_logs')))
pad_native=Articulation(make_articulation_cfg(artifact.usd_path,motion=motion,physical=physical,
 root_pose=root_pose,activate_contact_sensors=True))
material=suite.fixture['sphere_material'];settings=suite.settings
probe=RigidObject(RigidObjectCfg(prim_path='/World/Probe',
 spawn=sim_utils.SphereCfg(radius=settings['radius_m'],mass_props=sim_utils.MassPropertiesCfg(mass=settings['mass_kg']),
 rigid_props=sim_utils.RigidBodyPropertiesCfg(),
 collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=offsets['contact_offset_m'].value,rest_offset=offsets['rest_offset_m'].value),
 physics_material=sim_utils.RigidBodyMaterialCfg(**material)),
 init_state=RigidObjectCfg.InitialStateCfg(pos=(0.,0.,.15))))
if args.diagnostic_no_shell_contact:
    if not args.comparison_only:raise ValueError('shell isolation is diagnostic only')
    shell_prim=omni.usd.get_context().get_stage().GetPrimAtPath('/World/Gamepad/Links/controller_body')
    UsdPhysics.FilteredPairsAPI.Apply(shell_prim).CreateFilteredPairsRel().SetTargets(['/World/Probe'])
    result['diagnostic_shell_probe_contact_disabled']=True
links=sorted({'controller_body'}|{case.plan['link'] for case in suite.cases})
sensors={link:ContactSensor(ContactSensorCfg(prim_path='/World/Gamepad/Links/'+link,
 filter_prim_paths_expr=['/World/Probe'],track_contact_points=True,update_period=0.,max_contact_data_count_per_prim=64)) for link in links}
started=time.perf_counter();sim.reset();torch.cuda.synchronize();result['reset_and_cook_seconds']=time.perf_counter()-started
pad_native.update(.004);probe.update(.004)
pad=bind_articulation(pad_native,motion=motion,physical=physical)
result['root_pose_m_wxyz']=list(pad.root_pose().position_m)+list(pad.root_pose().orientation_wxyz)
assert np.allclose(result['root_pose_m_wxyz'],[*root_pose.position_m,*root_pose.orientation_wxyz],atol=1e-7)
executor=IsaacPressExecutor(simulation=sim,gamepad=pad,probe=probe,sensors=sensors,root_pose=root_pose,radius_m=settings['radius_m'])
if not args.full_suite and args.cases=='Guide':executor.diagnostic_links=['guide','controller_body']
result['shape_stats']=omni.physx.get_physxunittests_interface().get_physics_stats()
result['cooking_after_reset']=cooking();result['gpu_after_reset']=gpu()
stage=omni.usd.get_context().get_stage()
meshes=[p for p in stage.Traverse() if p.HasAPI(UsdPhysics.CollisionAPI) and '/Gamepad/' in str(p.GetPath())]
result['source_shapes']=len(meshes)
result['effective_contact_offsets']=[{'path':str(p.GetPath()),'contact':PhysxSchema.PhysxCollisionAPI(p).GetContactOffsetAttr().Get(),
 'rest':PhysxSchema.PhysxCollisionAPI(p).GetRestOffsetAttr().Get()} for p in meshes]
if args.collision=='sdf':
    view=tensors.create_simulation_view('torch');view.set_subspace_roots('/')
    from xbox_gamepad_physics.isaac.guide_clearance import SdfShapeCollection
    sdf=SdfShapeCollection([str(p.GetPath()) for p in meshes if UsdPhysics.MeshCollisionAPI(p).GetApproximationAttr().Get()=='sdf'],64)
    result['actual_sdf_shapes']=sdf.count;result['sdf_paths']=list(sdf.object_paths)
    save()
    expected_sdf=sum(UsdPhysics.MeshCollisionAPI(p).GetApproximationAttr().Get()=='sdf' for p in meshes)
    assert sdf.count==expected_sdf>0,('SDF shapes missing',sdf.count,expected_sdf)
    points=[];grid=[]
    for path in sdf.object_paths:
        p=stage.GetPrimAtPath(path);vertices=np.asarray(UsdGeom.Mesh(p).GetPointsAttr().Get(),dtype=np.float32)
        points.append(vertices[np.arange(64)%len(vertices)])
        extent=float(np.max(vertices.max(0)-vertices.min(0)))
        resolution=PhysxSchema.PhysxSDFMeshCollisionAPI(p).GetSdfResolutionAttr().Get()
        grid.append({'path':path,'resolution':resolution,'largest_extent_m':extent,'derived_spacing_m':extent/resolution})
    data=sdf.get_sdf_and_gradients(torch.tensor(np.asarray(points),device=args.device)).cpu().numpy()
    # Installed Sim 5.1 test_sdf_shape_view.py validates [:,:,-1] as distance
    # and [:,:,:3] as gradient; its public method docstring reverses that order.
    distances=data[:,:,-1]
    result['sdf_surface_query']={'samples_per_mesh':64,'finite':bool(np.isfinite(data).all()),
        'max_abs_distance_m':float(np.max(np.abs(distances))),'mean_abs_distance_m':float(np.mean(np.abs(distances))),
        'gradient_norm_median':float(np.median(np.linalg.norm(data[:,:,:3],axis=2))),
        'component_basis':'installed Sim5.1 analytic cube unit test: gradient xyz, distance w'}
    result['sdf_grids']=grid;save();assert np.isfinite(data).all()
else:
    repr_rows=[];stage_id=UsdUtils.StageCache.Get().GetId(stage).ToLongInt()
    for p in meshes:
        vertices=np.asarray(UsdGeom.Mesh(p).GetPointsAttr().Get(),dtype=np.float32)
        if len(vertices)<=64:continue
        record={'path':str(p.GetPath()),'source_vertices':len(vertices),'callback_received':False}
        def callback(status,convexes,record=record):
            record['callback_received']=True;record['cook_status']=str(status)
            record['cooked_vertices']=[len(h.vertices) for h in convexes]
            record['cooked_convexes']=len(convexes)
        omni.physx.get_physx_cooking_interface().request_convex_collision_representation(
            stage_id=stage_id,collision_prim_id=PhysicsSchemaTools.sdfPathToInt(str(p.GetPath())),
            run_asynchronously=False,on_result=callback)
        repr_rows.append(record)
    result['convex_above_64']=repr_rows;save()
    assert all(r['callback_received'] for r in repr_rows)

if args.measure_guide_clearance:
    from xbox_gamepad_physics.isaac.guide_clearance import measure_guide_clearance
    result['guide_clearance']=measure_guide_clearance(stage,sdf if args.collision=='sdf' else None,
        collisions=collisions,case=suite.case('Guide'),radius_m=settings['radius_m'],device=args.device)
    save()

# Shell contact from an actual frozen triangle; no substitute synthetic geometry.
from xbox_gamepad_physics.backends.common.collision import _objects
xy=np.array([-.0011641576666666666,-.02238319966666667])
hits=[]
for source in collisions:
    if source.component not in {'shell','shell_front_plate'}:continue
    for path in source.triangle_shells:
        for _,vertices,faces in _objects(source.root/path):
            triangles=np.asarray(vertices)[np.asarray(faces)]
            for tri in triangles:
                m=np.column_stack([tri[1,:2]-tri[0,:2],tri[2,:2]-tri[0,:2]])
                if abs(np.linalg.det(m))<1e-14:continue
                u,v=np.linalg.solve(m,xy-tri[0,:2])
                if u>=0 and v>=0 and u+v<=1:
                    hit=tri[0]+u*(tri[1]-tri[0])+v*(tri[2]-tri[0])
                    normal=np.cross(tri[1]-tri[0],tri[2]-tri[0]);normal/=np.linalg.norm(normal)
                    hits.append((hit,normal))
assert hits,'shell ray has no triangle intersections'
point,normal=max(hits,key=lambda pair:pair[0][2])
if normal[2]<0:normal=-normal
point=point+np.array(root_pose.position_m)
result['shell_fixture_intersection_z_local_m']=sorted(float(h[0][2]) for h in hits)
# Identical frozen triangle-shell source face for every collision variant.
executor.reset_case(suite,suite.cases[0])
state=probe.data.default_root_state.clone();state[0,:3]=torch.tensor(point+normal*(settings['radius_m']+.005),device=probe.device)
state[:,7:]=0;probe.write_root_state_to_sim(state);probe.reset()
contacts=[]
for _ in range(180):
    b=executor.ball_state();force=ball_force(settings,point-normal*.001,b['position_m'],b['velocity_m_s'],suite.fixture['gravity_m_s2'])
    executor.apply_ball_force(force);executor.step(.004)
    contacts.extend(c for c in executor.sample()['contacts'] if c['link']=='controller_body')
result['shell_contact']={'observed':bool(contacts),'sample_count':len(contacts),'fixture_point_m':point.tolist(),
 'fixture_normal':normal.tolist(),'radial_residual_max_abs_m':max((abs(c['contact_point_radial_residual_m']) for c in contacts if c['contact_point_radial_residual_m'] is not None),default=None)}
save()
if not args.diagnostic_no_shell_contact:assert contacts,'shell contact missing'
cases=suite.cases if args.full_suite else [suite.case(name) for name in args.cases.split(',')]
if args.full_suite:cases=cases[args.case_start:args.case_start+args.case_count if args.case_count is not None else None]
for case in cases:
    sink=ResultSink(args.output/('trace_'+case.case_id+'.jsonl'))
    scored=run_case(executor,suite,case,sink);sink.close()
    rows=[json.loads(line) for line in (args.output/('trace_'+case.case_id+'.jsonl')).read_text().splitlines()]
    contacts=[c for row in rows for c in row['contacts'] if c['link']==case.plan['link']]
    scored['target_contact_observed']=bool(contacts)
    scored['contact_point_radial_residual_max_abs_m']=max((abs(c['contact_point_radial_residual_m']) for c in contacts if c['contact_point_radial_residual_m'] is not None),default=None)
    scored['baseline_passed']=case.baseline['passed'];scored['baseline_target_min']=case.baseline['target_min']
    hold=[row for row in rows if row['probe']['phase']=='hold'][-125:]
    scored['hold_contact_by_link']={link:{'active_samples':sum(any(c['link']==link for c in row['contacts']) for row in hold),
      'peak_force_n':max((math.sqrt(sum(x*x for x in c['force_n'])) for row in hold for c in row['contacts'] if c['link']==link),default=None)}
      for link in sorted({c['link'] for row in hold for c in row['contacts']})}
    result['cases'].append(scored);save()
    if not args.full_suite and not args.comparison_only:
        assert contacts,('dynamic link contact missing',case.case_id)
    if args.full_suite and not args.comparison_only and case.baseline['passed'] and not scored['physics_passed']:
        result['status']='failed_regression';result['failed_case']=case.case_id;save()
        raise AssertionError('previously passed case regressed: '+case.case_id)
result['cooking_final']=cooking();result['gpu_final']=gpu();result['status']='completed_comparison' if args.comparison_only else 'passed';result['physics_passed_count']=sum(c['physics_passed'] for c in result['cases']);save()
print('B3_DONE '+args.collision+' '+str(args.spacing_mm),flush=True)
app.close(skip_cleanup=True)
