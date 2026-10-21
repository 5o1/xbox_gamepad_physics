"""Native CUDA row-isolation checks; owns its entire app and scene."""
import argparse
import json
from pathlib import Path
import time
from isaaclab.app import AppLauncher
parser=argparse.ArgumentParser()
parser.add_argument('--resources',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--num-envs',type=int,choices=[1,64],required=True)
AppLauncher.add_app_launcher_args(parser)
args=parser.parse_args();launcher=AppLauncher(args);app=launcher.app

import torch
from isaaclab.sim import SimulationContext,SimulationCfg
from isaaclab.scene import InteractiveScene,InteractiveSceneCfg
from isaaclab.utils import configclass
from xbox_gamepad_physics.isaac import build_usd,make_articulation_cfg,bind_batched_articulation,step
from xbox_gamepad_physics.motion import motion_from_dict
from xbox_gamepad_physics.backends.common.appearance import load_appearance
from xbox_gamepad_physics.backends.common.collision import load_collision_sources
from xbox_gamepad_physics.backends.common.physical import load_physical
from xbox_gamepad_physics.backends.common.handle import ResetRequest
from xbox_gamepad_physics.backends.common.signals_torch import NamedJointBatch,SignalBatch
from dataclasses import fields

args.output.mkdir(parents=True,exist_ok=True)
r=args.resources;c=r/'common/xbox_one_s'
motion=motion_from_dict(json.loads((c/'motion/full_controls.json').read_text()))
physical=load_physical(resource_directory=c/'physical')
appearance=load_appearance(directory=c/'visual',binding=json.loads((r/'review_binding.json').read_text()))
artifact=build_usd(args.output/'batch.usda',motion=motion,physical=physical,appearance=appearance,
 collision_sources=load_collision_sources(directory=c/'collision'),visual_directory=c/'visual',root_mode='free',collision_mode='coacd')
sim=SimulationContext(SimulationCfg(dt=.004,device=args.device,gravity=(0.,0.,0.),log_dir=str(args.output/'lab_logs')))
@configclass
class SceneCfg(InteractiveSceneCfg):
    pad=make_articulation_cfg(artifact.usd_path,motion=motion,physical=physical,prim_path='{ENV_REGEX_NS}/Gamepad')
started=time.perf_counter()
scene=InteractiveScene(SceneCfg(num_envs=args.num_envs,env_spacing=.25,replicate_physics=True))
sim.reset();scene.update(.004)
native=scene['pad']
pad=bind_batched_articulation(native,motion=motion,physical=physical,env_origins=scene.env_origins)
n=pad.num_envs;j=len(pad.joint_names);device=pad.device
root=torch.zeros((n,7),device=device);root[:,3]=1
zero_v=torch.zeros((n,j),device=device);zero_twist=torch.zeros((n,6),device=device)
pad.reset(ResetRequest(root_pose=root,root_twist=zero_twist))
checks={}
def save_partial(status='running'):
    (args.output/'result.json').write_text(json.dumps({'status':status,'num_envs':n,'checks':checks},indent=2)+'\n')
def same(label,actual,expected,atol=0):
    delta=float((actual-expected).abs().max().item()) if actual.numel() else 0.
    checks[label]={'max_abs':delta,'elements':actual.numel()}
    passed=torch.allclose(actual,expected,atol=atol,rtol=0)
    save_partial('running' if passed else 'failed')
    assert passed,(label,delta)

def expect_reject(label,func):
    try:func()
    except (ValueError,TypeError):checks[label]={'rejected':True};return
    raise AssertionError(label+' was accepted')

same('root_local_origin_once',pad.root_poses(),root,atol=2e-7)
borrow=pad.joint_positions(copy=False);owned=pad.joint_positions()
assert borrow.data_ptr()==native.data.joint_pos.data_ptr() and owned.data_ptr()!=borrow.data_ptr()
checks['borrow_copy']={'native_alias':True,'copy_independent':True}
lo=torch.tensor([motion.joint_by_name[x].lower for x in pad.joint_names],device=device)
hi=torch.tensor([motion.joint_by_name[x].upper for x in pad.joint_names],device=device)
fraction=(torch.arange(n,device=device)[:,None]+torch.arange(j,device=device)[None,:]*.37+1)/(n+j*.37+2)
q=lo+(hi-lo)*fraction
# D08 uses legal interior states for row isolation. Actual cone boundary loads
# and rejection of the independent-axis corner belong to check_shaft_limits.py.
for side in ('left','right'):
    for axis in ('x','y'):
        q[:,pad._indices[side+'_stick_'+axis]]*=.5
pad.set_joint_positions(q)
same('all_distinct_rows',pad.joint_positions(),q)
same('owning_copy_unchanged',owned,torch.zeros_like(owned))
rev=tuple(reversed(pad.joint_names));pad.set_joint_positions(NamedJointBatch(rev,q.flip(1)))
same('joint_name_order',pad.joint_positions(),q)
perm=torch.arange(n-1,-1,-1,device=device)
subset=list(range(n-1,-1,-2))
same('subset_order',pad.joint_positions(subset),q[subset])
assert pad.joint_positions([]).shape==(0,j)
empty=pad.gamepad_state([]);assert empty.values.shape==(0,32)
pad.set_gamepad_state(empty,[]);pad.reset(ResetRequest(),[])
for label,ids in [('duplicate',[0,0]),('negative',[-1]),('overflow',[n]),('noninteger',[.5])]:
    expect_reject(label,lambda ids=ids:pad.joint_positions(ids))
expect_reject('implicit_broadcast',lambda:pad.set_joint_positions(q[:1],list(range(n))) if n>1 else pad.set_joint_positions(q.reshape(-1)))
state=pad.mapper.encode(q)
expected=q.clone();decoded=pad.mapper.decode_joint_targets(state)
columns=[pad.joint_names.index(x) for x in decoded.names];expected[:,columns]=decoded.values
pair=[i for i,x in enumerate(pad.joint_names) if x not in decoded.names]
pad.set_gamepad_state(state)
same('state_write',pad.joint_positions(),expected)
same('pair_preserved',pad.joint_positions()[:,pair],q[:,pair])
old=pad.joint_positions()
selected=pad.mapper.encode(q[subset])
pad.set_gamepad_state(selected,subset)
others=[i for i in range(n) if i not in subset]
same('subset_other_rows',pad.joint_positions()[others],old[others])
pad.set_gamepad_targets(state)
targets_before=native.data.joint_pos_target.clone()
k=n//2
q_before=pad.joint_positions();v_before=pad.joint_velocities();root_before=pad.root_poses()
pad.reset(ResetRequest(),[k])
others=[i for i in range(n) if i!=k]
same('reset_k_other_q',pad.joint_positions()[others],q_before[others])
same('reset_k_other_v',pad.joint_velocities()[others],v_before[others])
same('reset_k_other_targets',native.data.joint_pos_target[others],targets_before[others])
same('reset_k_other_root',pad.root_poses()[others],root_before[others])
same('reset_k_q',pad.joint_positions([k]),torch.zeros((1,j),device=device))
same('selected_scalar',torch.tensor([list(pad.select(k).joint_positions().values())],device=device),pad.joint_positions([k]))
local=root.clone();local[:,:3]=torch.stack((torch.linspace(.001,.009,n,device=device),torch.zeros(n,device=device),torch.zeros(n,device=device)),1)
pad.reset(ResetRequest(root_pose=local,root_twist=zero_twist,joint_positions=q,joint_velocities=zero_v))
same('root_write_read_origin_once',pad.root_poses(),local,atol=2e-7)

# Same rows and targets, only physical row assignment changes. Compare after
# equal stepping; the fixture disables inter-environment collisions explicitly.
def advance(initial,targets):
    pad.reset(ResetRequest(root_pose=root,root_twist=zero_twist,joint_positions=initial,joint_velocities=zero_v))
    pad.set_joint_targets(targets)
    for _ in range(20):step(sim,gamepads=(pad,))
    return pad.joint_positions(),pad.root_poses()
q_first,r_first=advance(q,lo+(hi-lo)*(1-fraction))
q_second,r_second=advance(q[perm],(lo+(hi-lo)*(1-fraction))[perm])
# Global cloned origins incur float32 position quantization; report in SI.
same('stepped_row_permutation_q_normalized',q_second/(hi-lo),q_first[perm]/(hi-lo),atol=2e-4)
same('stepped_row_permutation_root',r_second[:,:3],r_first[perm,:3],atol=3e-6)
result={'status':'passed','num_envs':n,'joint_names':pad.joint_names,'checks':checks,
 'seconds':time.perf_counter()-started,'torch_allocated_bytes':torch.cuda.memory_allocated(),
 'torch_reserved_bytes':torch.cuda.memory_reserved(),'gravity_m_s2':[0,0,0],
 'fixture_note':'isolated drive/row test; no contact validation',
 'replicate_physics':True,'filter_collisions':True}
(args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print('B2_DONE '+str(n),flush=True)
app.close(skip_cleanup=True)
