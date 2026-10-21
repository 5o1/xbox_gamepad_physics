"""Native batched articulation access; the caller owns flush/update/step."""
from __future__ import annotations

from dataclasses import fields
import math
import torch

from ..backends.common.handle import ResetRequest, SignalHandleMixin, validate_env_ids
from ..backends.common.model import Pose
from ..backends.common.signals_torch import NamedJointBatch, SignalBatch
from .signals_torch import IsaacTorchSignalMapper
from .constraints import require_supported_constraints, verify_native_cones


class IsaacBatchedGamepadHandle:
    """Bind existing native rows without creating environments or stepping.

    Joint/root reads with copy=False are borrowed until the next caller update
    or write. Full/contiguous joint reads alias native buffers; reordered subsets
    are a gathered borrowed tensor. copy=True always owns independent storage.
    Root positions are environment-local; velocities use world-aligned axes.
    """
    asset_id = 'xbox_one_s'
    backend = 'isaac'
    profile = 'full_controls'
    capabilities = frozenset({'named_joints','signals','birth_fixed_free','batch_cuda'})

    def __init__(self, articulation, *, motion, physical, env_origins):
        require_supported_constraints(motion)
        if not articulation.is_initialized:
            raise ValueError('bind after the caller initializes the articulation')
        self.articulation=articulation
        self.motion=motion
        self.physical=physical
        self.num_envs=articulation.num_instances
        self.device=torch.device(articulation.device)
        self.dtype=articulation.data.joint_pos.dtype
        self.joint_names=tuple(articulation.joint_names)
        if len(set(self.joint_names))!=len(self.joint_names) or set(self.joint_names)!=set(motion.joint_by_name):
            raise ValueError('native and common motion joint names differ')
        self._indices={n:i for i,n in enumerate(self.joint_names)}
        self._check(env_origins, self.num_envs, 3)
        self.env_origins=env_origins.clone()
        self.mapper=IsaacTorchSignalMapper(motion,self.joint_names,device=self.device,dtype=self.dtype)
        self._passive=torch.tensor([physical.return_laws[n].neutral_target.value for n in self.joint_names],device=self.device,dtype=self.dtype)
        self._initial=torch.tensor([physical.return_laws[n].initial_position.value for n in self.joint_names],device=self.device,dtype=self.dtype)
        verify_native_cones(articulation,motion)
        from .shaft_limits import ShaftLimits
        self._shaft_limits=ShaftLimits(articulation,motion)
        self._shaft_limits.validate_initial_state()

    def _check(self,value,rows,width):
        if not isinstance(value,torch.Tensor) or value.device!=self.device or value.dtype!=self.dtype or tuple(value.shape)!=(rows,width):
            raise ValueError(f'expected [{rows},{width}] {self.dtype} on {self.device}; no implicit broadcast/conversion')
        if not bool(torch.isfinite(value).all()):
            raise ValueError('tensor values must be finite')

    def _ids(self,env_ids):
        if isinstance(env_ids,torch.Tensor):
            if env_ids.device!=self.device or env_ids.dtype!=torch.int64 or env_ids.ndim!=1:
                raise ValueError('env_ids tensor must be int64 [K] on the handle device')
            if bool(((env_ids<0)|(env_ids>=self.num_envs)).any()) or torch.unique(env_ids).numel()!=env_ids.numel():
                raise ValueError('env_ids must be unique and in range')
            return env_ids
        ids=validate_env_ids(env_ids,self.num_envs)
        return torch.tensor(ids,device=self.device,dtype=torch.int64)

    def _read(self,tensor,env_ids,copy):
        if env_ids is None:
            selected=tensor
        elif isinstance(env_ids,(tuple,list,range)) and len(env_ids)>0 and tuple(env_ids)==tuple(range(env_ids[0],env_ids[0]+len(env_ids))):
            self._ids(env_ids)
            selected=tensor[env_ids[0]:env_ids[0]+len(env_ids)]
        else:
            selected=tensor[self._ids(env_ids)]
        return selected.clone() if copy else selected

    def joint_positions(self,env_ids=None,*,copy=True):
        return self._read(self.articulation.data.joint_pos,env_ids,copy)

    def joint_velocities(self,env_ids=None,*,copy=True):
        return self._read(self.articulation.data.joint_vel,env_ids,copy)

    def gamepad_state(self,env_ids=None,*,task_mask=None,copy=True):
        result=self.mapper.encode(self.joint_positions(env_ids,copy=False),task_mask=task_mask)
        if not copy:return result
        return SignalBatch(**{f.name:(getattr(result,f.name).clone() if isinstance(getattr(result,f.name),torch.Tensor) else getattr(result,f.name)) for f in fields(SignalBatch)})

    def _named(self,value,ids,*,targets=False):
        if isinstance(value,NamedJointBatch):
            names=tuple(value.names);values=value.values
        else:
            names=self.joint_names;values=value
        if len(names)!=len(set(names)) or not set(names)<=set(self._indices):
            raise ValueError('unknown or duplicate joint columns')
        self._check(values,len(ids),len(names))
        columns=torch.tensor([self._indices[n] for n in names],device=self.device,dtype=torch.int64)
        lower=torch.tensor([self.motion.joint_by_name[n].lower for n in names],device=self.device,dtype=self.dtype)
        upper=torch.tensor([self.motion.joint_by_name[n].upper for n in names],device=self.device,dtype=self.dtype)
        invalid=(values<lower)|(values>upper)
        if targets:
            invalid &= values!=self._passive[columns]
        if bool(invalid.any()):raise ValueError('named joint values exceed motion limits')
        return columns,values

    def set_joint_positions(self,positions,env_ids=None):
        ids=self._ids(env_ids);columns,values=self._named(positions,ids)
        if not len(ids):return
        q=self.articulation.data.joint_pos[ids].clone()
        v=self.articulation.data.joint_vel[ids].clone()
        q[:,columns]=values
        q=self._shaft_limits.checked_state(q,v)
        self.articulation.write_joint_state_to_sim(q,v,env_ids=ids)

    def set_joint_targets(self,targets,env_ids=None):
        ids=self._ids(env_ids);columns,values=self._named(targets,ids,targets=True)
        if not len(ids):return
        self.articulation.set_joint_position_target(values,joint_ids=columns,env_ids=ids)

    def set_gamepad_state(self,state,env_ids=None):
        ids=self._ids(env_ids)
        if state.values.shape[0]!=len(ids):raise ValueError('state row count differs from env_ids')
        self.set_joint_positions(self.mapper.decode_joint_targets(state),ids)

    def set_gamepad_targets(self,state,env_ids=None):
        ids=self._ids(env_ids)
        if state.values.shape[0]!=len(ids):raise ValueError('target row count differs from env_ids')
        self.set_joint_targets(self.mapper.decode_joint_targets(state),ids)

    def set_physical_events(self,events,env_ids=None):
        ids=self._ids(env_ids)
        if events.shape[0]!=len(ids):raise ValueError('event row count differs from env_ids')
        self.set_joint_positions(self.mapper.decode_event_targets(events),ids)

    def root_poses(self,env_ids=None,*,copy=True):
        result=self._read(self.articulation.data.root_state_w[:,:7],env_ids,True)
        result[:,:3]-=self._read(self.env_origins,env_ids,False)
        return result

    def root_twists(self,env_ids=None,*,copy=True):
        return self._read(self.articulation.data.root_state_w[:,7:13],env_ids,copy)

    def restore_passive_targets(self,env_ids=None):
        ids=self._ids(env_ids)
        if len(ids):self.articulation.set_joint_position_target(self._passive.expand(len(ids),-1),env_ids=ids)

    def reset(self,request=ResetRequest(),env_ids=None):
        ids=self._ids(env_ids);k=len(ids)
        if request.targets not in {'passive','retain'}:raise ValueError('unknown reset target policy')
        if self.articulation.is_fixed_base and (request.root_pose is not None or request.root_twist is not None):
            raise ValueError('fixed roots cannot move after birth')
        q=self._initial.expand(k,-1).clone()
        v=torch.zeros_like(q)
        if request.joint_positions is not None:
            columns,values=self._named(request.joint_positions,ids);q[:,columns]=values
        if request.joint_velocities is not None:
            self._check(request.joint_velocities,k,len(self.joint_names));v=request.joint_velocities
        root_pose=request.root_pose
        if root_pose is not None:
            self._check(root_pose,k,7)
            if not bool(torch.isclose(torch.linalg.vector_norm(root_pose[:,3:],dim=1),torch.ones(k,device=self.device),atol=1e-6,rtol=1e-6).all()):
                raise ValueError('root quaternions must be normalized')
            root_pose=root_pose.clone();root_pose[:,:3]+=self.env_origins[ids]
        if request.root_twist is not None:self._check(request.root_twist,k,6)
        if not k:return
        q=self._shaft_limits.checked_state(q,v)
        if root_pose is not None:self.articulation.write_root_pose_to_sim(root_pose,env_ids=ids)
        if request.root_twist is not None:self.articulation.write_root_velocity_to_sim(request.root_twist,env_ids=ids)
        self.articulation.write_joint_state_to_sim(q,v,env_ids=ids)
        self.articulation.reset(env_ids=ids)
        if request.targets=='passive':self.restore_passive_targets(ids)

    def select(self,env_id):
        validate_env_ids((env_id,),self.num_envs)
        return _SelectedHandle(self,env_id)


class _SelectedHandle(SignalHandleMixin):
    asset_id='xbox_one_s';backend='isaac';profile='full_controls'
    capabilities=IsaacBatchedGamepadHandle.capabilities
    def __init__(self,batch,index):
        self.batch=batch;self.index=index;self._signal_controller=batch.motion.signal_controller
    @property
    def joint_names(self):return self.batch.joint_names
    @property
    def root_fixed(self):return bool(self.batch.articulation.is_fixed_base)
    def joint_positions(self):
        values=self.batch.joint_positions([self.index])[0].cpu().tolist()
        return dict(zip(self.joint_names,values))
    def joint_position(self,name):return self.joint_positions()[name]
    def joint_velocity(self,name):return float(self.batch.joint_velocities([self.index])[0,self.batch._indices[name]].item())
    def _pack(self,positions):
        return NamedJointBatch(tuple(positions),torch.tensor([list(positions.values())],device=self.batch.device,dtype=self.batch.dtype))
    def set_joint_positions(self,positions):self.batch.set_joint_positions(self._pack(positions),[self.index])
    def set_joint_target(self,name,target):self.batch.set_joint_targets(self._pack({name:target}),[self.index])
    def restore_passive_targets(self):self.batch.restore_passive_targets([self.index])
    def root_pose(self):
        p=self.batch.root_poses([self.index])[0].cpu().tolist();q=p[3:];norm=math.sqrt(sum(v*v for v in q))
        return Pose(tuple(p[:3]),tuple(v/norm for v in q))
    def root_twist(self):return tuple(self.batch.root_twists([self.index])[0].cpu().tolist())
    def reset(self,request=ResetRequest()):
        p=request.root_pose
        root=None if p is None else torch.tensor([[*p.position_m,*p.orientation_wxyz]],device=self.batch.device,dtype=self.batch.dtype)
        twist=None if request.root_twist is None else torch.tensor([request.root_twist],device=self.batch.device,dtype=self.batch.dtype)
        q=None if request.joint_positions is None else self._pack(request.joint_positions)
        v=None
        if request.joint_velocities is not None:
            v=torch.zeros((1,len(self.joint_names)),device=self.batch.device,dtype=self.batch.dtype)
            for name,value in request.joint_velocities.items():v[0,self.batch._indices[name]]=value
        self.batch.reset(ResetRequest(root,twist,q,v,request.targets),[self.index])


def bind_batched_articulation(articulation,*,motion,physical,env_origins):
    print("Isaac backend preview: see docs/isaac_backend.md for known limitations.")
    return IsaacBatchedGamepadHandle(articulation,motion=motion,physical=physical,env_origins=env_origins)
