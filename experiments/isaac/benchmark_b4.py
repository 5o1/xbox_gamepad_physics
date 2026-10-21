"""Short no-render Isaac expansion curve with explicit native timing boundaries."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from isaaclab.app import AppLauncher
parser=argparse.ArgumentParser()
parser.add_argument('--resources',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--num-envs',type=int,choices=[1,64,1024],required=True)
parser.add_argument('--collision',choices=['coacd','sdf'],required=True)
parser.add_argument('--external-snapshot',type=Path,required=True)
parser.add_argument('--warmup',type=int,default=20)
parser.add_argument('--steps',type=int,default=100)
AppLauncher.add_app_launcher_args(parser)
args=parser.parse_args();launcher=AppLauncher(args);app=launcher.app

import torch
import omni.physx
from isaaclab.sim import SimulationContext,SimulationCfg
from isaaclab.scene import InteractiveScene,InteractiveSceneCfg
from isaaclab.utils import configclass
from xbox_gamepad_physics.isaac import build_usd,make_articulation_cfg,bind_batched_articulation,step
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.backends.common.appearance import load_appearance
from xbox_gamepad_physics.backends.common.collision import load_collision_sources
from xbox_gamepad_physics.backends.common.physical import load_physical
from xbox_gamepad_physics.backends.common.model import Evidence,Parameter
from tests.acceptance.cases import load_suite

args.output.mkdir(parents=True,exist_ok=True)
result={'status':'running','num_envs':args.num_envs,'collision':args.collision,'rendering':False,
 'camera_count':0,'warmup_steps':args.warmup,'measurement_steps':args.steps,
 'completed_steps':0,'external_load_before_launch':args.external_snapshot.read_text().strip(),'memory_samples':[]}
def save():
    (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
def memory(label):
    raw=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip()
    sample={'phase':label,'gpu_total_used_mib':int(raw.split(',')[0]),'nvidia_smi':raw,
      'torch_allocated_bytes':torch.cuda.memory_allocated(),'torch_reserved_bytes':torch.cuda.memory_reserved()}
    result['memory_samples'].append(sample);save()
def cooking():
    c=omni.physx.get_physx_cooking_private_interface().get_cooking_statistics()
    return {k:getattr(c,k) for k in ['total_scheduled_tasks','total_finished_tasks','total_finished_cache_hit_tasks','total_finished_cache_miss_tasks','total_warnings_failed_gpu_compatibility']}
c=args.resources/'common/xbox_one_s'
motion=motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()))
physical=load_physical(resource_directory=c/'physical')
appearance=load_appearance(directory=c/'visual',binding=json.loads((args.resources/'review_binding.json').read_text()))
suite=load_suite()
proof=Evidence('tests/acceptance/data/ruling20_sdf303_v1.json','fixture.sapien_mapping',
 'Same frozen offsets across performance variants.', 'Copy the explicit metre values; no fitting.',category='fixture_definition')
offsets={k:Parameter(suite.fixture['sapien_mapping'][k],'m',(proof,)) for k in ['contact_offset_m','rest_offset_m']}
options={'spacing_m':.0005,'subgrid_resolution':6,'bits_per_pixel':'BitsPerPixel16','margin':.01,'narrow_band_thickness':.02} if args.collision=='sdf' else None
artifact=build_usd(args.output/'controller.usda',motion=motion,physical=physical,appearance=appearance,
 collision_sources=load_collision_sources(directory=c/'collision'),visual_directory=c/'visual',root_mode='fixed',
 collision_mode=args.collision,sdf_options=options,contact_offsets=offsets)
sim=SimulationContext(SimulationCfg(dt=.004,device=args.device,gravity=(0.,0.,-9.81),log_dir=str(args.output/'lab_logs')))
@configclass
class SceneCfg(InteractiveSceneCfg):
    pad=make_articulation_cfg(artifact.usd_path,motion=motion,physical=physical,prim_path='{ENV_REGEX_NS}/Gamepad')
started=time.perf_counter()
scene=InteractiveScene(SceneCfg(num_envs=args.num_envs,env_spacing=.25,replicate_physics=True))
result['scene_author_and_clone_seconds']=time.perf_counter()-started
memory('before_native_load');result['cooking_before']=cooking()
# Native force-load is the supported parse/cook boundary. The SDK exposes no
# isolated cook-only timer: do not relabel this inclusive time as pure cooking.
torch.cuda.synchronize();started=time.perf_counter()
omni.physx.get_physx_interface().force_load_physics_from_usd()
torch.cuda.synchronize();result['parse_and_cook_seconds']=time.perf_counter()-started
result['cooking_after_load']=cooking();memory('after_native_load')
started=time.perf_counter();sim.reset();torch.cuda.synchronize()
result['initialize_reset_seconds']=time.perf_counter()-started
scene.update(.004)
pad=bind_batched_articulation(scene['pad'],motion=motion,physical=physical,env_origins=scene.env_origins)
result['native_num_envs']=pad.num_envs;assert pad.num_envs==args.num_envs
result['cooking_after_initialize']=cooking();memory('after_initialize')
pad.restore_passive_targets()
for _ in range(args.warmup):step(sim,gamepads=(pad,))
torch.cuda.synchronize();started=time.perf_counter()
for _ in range(10):pad.reset()
torch.cuda.synchronize();result['state_reset_seconds_mean']=float((time.perf_counter()-started)/10)
result['state_reset_repetitions']=10
started=time.perf_counter()
for _ in range(args.steps):step(sim,gamepads=(pad,))
torch.cuda.synchronize();result['step_window_seconds']=time.perf_counter()-started
result['step_seconds_mean']=result['step_window_seconds']/args.steps
result['world_steps_per_second']=args.steps/result['step_window_seconds']
result['environment_steps_per_second']=args.num_envs*result['world_steps_per_second']
result['completed_steps']=args.steps
result['finite_joint_state']=bool(torch.isfinite(pad.joint_positions(copy=False)).all() & torch.isfinite(pad.joint_velocities(copy=False)).all())
assert result['finite_joint_state']
result['shape_stats']=omni.physx.get_physxunittests_interface().get_physics_stats()
result['cooking_final']=cooking();memory('after_measurement')
result['max_sampled_gpu_total_used_mib']=max(x['gpu_total_used_mib'] for x in result['memory_samples'])
result['cook_only_seconds']=None
result['cook_only_missing_reason']='SDK exposes no isolated timer; parse_and_cook includes native population and cooking; any subsequent cook tasks are listed after initialize.'
result['scene']={'dt_s':.004,'root_mode':'fixed','env_spacing_m':.25,'replicate_physics':True,'filter_collisions':True,
 'objects_per_env':'one controller, no probe/table','solver':'unchanged external platform defaults','gravity_m_s2':[0,0,-9.81]}
result['status']='passed';save();print('BENCH_DONE '+args.collision+' '+str(args.num_envs),flush=True)
app.close(skip_cleanup=True)
