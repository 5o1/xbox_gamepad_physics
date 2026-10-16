"""Optional CPU tensor execution of the canonical scalar controller semantics.

Torch is an external prerequisite, imported only on explicit module use. All
arithmetic and branch decisions use float64; outputs preserve the requested
float32/float64 dtype. CUDA verification belongs to the Isaac implementation.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import torch
from ...errors import StateValidationError
from ...state import CHANNEL_NAMES


@dataclass(frozen=True)
class SignalBatch:
    values: torch.Tensor
    available_mask: torch.Tensor
    task_mask: torch.Tensor
    action_mask: torch.Tensor
    device_id: torch.Tensor
    events: torch.Tensor
    event_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class NamedJointBatch:
    names: tuple[str, ...]
    values: torch.Tensor


class TorchSignalMapper:
    def __init__(self, motion, joint_names, *, device="cpu", dtype=torch.float64):
        self.motion = motion
        self.controller = motion.signal_controller
        self.joint_names = tuple(joint_names)
        self.device = torch.device(device)
        self.dtype = dtype
        if self.device.type != "cpu":
            raise NotImplementedError("C1 verifies CPU tensors only; CUDA requires the Isaac validation stage")
        if dtype not in (torch.float32,torch.float64):
            raise ValueError("mapper dtype must be float32 or float64")
        if len(set(self.joint_names)) != len(self.joint_names):
            raise ValueError("duplicate joint names")
        self.indices = {name:i for i,name in enumerate(self.joint_names)}
        self.channels = {name:i for i,name in enumerate(CHANNEL_NAMES)}
        c = self.controller
        required = {m.source for group in (c.axis_mappings,c.scalar_mappings,c.split_mappings,c.physical_event_mappings) for m in group}
        if not required <= set(self.indices):
            raise ValueError(f"missing mapped joints: {sorted(required-set(self.indices))}")
        self.available = torch.tensor([name in c.available_channels for name in CHANNEL_NAMES],device=self.device,dtype=torch.bool)
        self.event_names = tuple(m.event for m in c.physical_event_mappings)

    def _check(self, value, width):
        if (not isinstance(value,torch.Tensor) or value.ndim != 2 or value.shape[1] != width
                or value.device != self.device or value.dtype != self.dtype):
            raise StateValidationError(f"expected [N,{width}] {self.dtype} on {self.device}")
        if not bool(torch.isfinite(value).all()):
            raise StateValidationError("tensor values must be finite")

    def _radial(self, first, second, group):
        radius = torch.hypot(first,second)
        # CPython math.hypot is the branch oracle. Only boundary-adjacent CPU
        # rows need its correctly rounded decision; normal rows stay vectorized.
        near = ((radius-group.neutral_epsilon).abs() <= 16*math.ulp(max(group.neutral_epsilon,1e-300))) | ((radius-group.radius).abs() <= 16*math.ulp(group.radius))
        if bool(near.any()):
            radius = radius.clone()
            for index in near.nonzero().flatten().tolist():
                radius[index] = math.hypot(float(first[index]),float(second[index]))
        neutral = radius <= group.neutral_epsilon
        factor = torch.where(radius>group.radius,group.radius/radius.clamp_min(1e-300),torch.ones_like(radius))
        return torch.where(neutral,0.,first*factor),torch.where(neutral,0.,second*factor)

    def encode(self, joint_pos, *, task_mask=None):
        self._check(joint_pos,len(self.joint_names))
        q=joint_pos.to(torch.float64)
        n=q.shape[0]
        values=torch.zeros((n,32),dtype=torch.float64,device=self.device)
        c=self.controller
        for mapping in c.axis_mappings:
            raw=q[:,self.indices[mapping.source]]
            scale=torch.where(raw<0,torch.full_like(raw,-mapping.lower),torch.full_like(raw,mapping.upper))
            values[:,self.channels[mapping.channel]]=(raw/scale).clamp(-1,1)
        for mapping in c.scalar_mappings:
            normalized=((q[:,self.indices[mapping.source]]-mapping.lower)/(mapping.upper-mapping.lower)).clamp(0,1)
            values[:,self.channels[mapping.channel]]=torch.where(normalized<=mapping.neutral_epsilon,0.,normalized)
        split={}
        for mapping in c.split_mappings:
            raw=q[:,self.indices[mapping.source]]
            split[mapping.source]=(raw/torch.where(raw<0,torch.full_like(raw,-mapping.lower),torch.full_like(raw,mapping.upper))).clamp(-1,1)
        for group in c.radial_source_groups:
            a,b=group.sources
            split[a],split[b]=self._radial(split[a],split[b],group)
        for mapping in c.split_mappings:
            values[:,self.channels[mapping.negative_channel]]=torch.clamp(-split[mapping.source],min=0)
            values[:,self.channels[mapping.positive_channel]]=torch.clamp(split[mapping.source],min=0)
        for group in c.radial_groups:
            a,b=(self.channels[name] for name in group.channels)
            values[:,a],values[:,b]=self._radial(values[:,a].clone(),values[:,b].clone(),group)
        threshold=c.dpad_contact_threshold
        adjacent=torch.zeros(n,dtype=torch.bool,device=self.device)
        if threshold is not None:
            for name in ("dpad_up","dpad_down","dpad_left","dpad_right"):
                if name in c.available_channels:
                    index=self.channels[name]
                    adjacent |= (values[:,index]-threshold).abs() <= 32*math.ulp(threshold)
                    values[:,index]=torch.where(values[:,index]<threshold,0.,values[:,index])
        # Projection followed by a discontinuous closure can amplify a 1-ulp
        # hypot difference. Re-evaluate only those boundary rows with the oracle.
        for row in adjacent.nonzero().flatten().tolist():
            state=c.encode({name:float(q[row,index]) for name,index in self.indices.items()})
            values[row]=torch.tensor(state.values,dtype=torch.float64,device=self.device)
        events=torch.empty((n,len(c.physical_event_mappings)),dtype=torch.float64,device=self.device)
        for index,mapping in enumerate(c.physical_event_mappings):
            events[:,index]=((q[:,self.indices[mapping.source]]-mapping.lower)/(mapping.upper-mapping.lower)).clamp(0,1)
        available=self.available.expand(n,-1).clone()
        if task_mask is None:
            task=available.clone()
        else:
            if not isinstance(task_mask,torch.Tensor) or task_mask.dtype != torch.bool or task_mask.device != self.device:
                raise StateValidationError("task mask must be a bool tensor on the mapper device")
            if tuple(task_mask.shape)==(32,):
                task=task_mask.expand(n,-1).clone()
            elif tuple(task_mask.shape)==(n,32):
                task=task_mask.clone()
            else:
                raise StateValidationError("task mask must have shape [32] or [N,32]")
            if bool((task & ~available).any()):
                raise StateValidationError("task mask exceeds available channels")
        return SignalBatch(values.to(self.dtype),available,task,available&task,
                           torch.full((n,),int(c._device_id),dtype=torch.int64,device=self.device),events.to(self.dtype),self.event_names)

    def _validate_state(self,state):
        self._check(state.values,32)
        n=state.values.shape[0]
        for mask in (state.available_mask,state.task_mask,state.action_mask):
            if (mask.dtype!=torch.bool or mask.device!=self.device or tuple(mask.shape)!=(n,32)):
                raise StateValidationError("state masks must be bool [N,32] tensors on the mapper device")
        expected=self.available.expand(n,-1)
        if not torch.equal(state.available_mask,expected) or bool((state.task_mask&~expected).any()):
            raise StateValidationError("state capability/task mask mismatch")
        if not torch.equal(state.action_mask,state.available_mask&state.task_mask):
            raise StateValidationError("incorrect action mask")
        lower=torch.zeros(32,dtype=torch.float64,device=self.device);lower[:4]=-1
        values=state.values.to(torch.float64)
        if bool(((values<lower)|(values>1)|(values.masked_fill(expected,0)!=0)).any()):
            raise StateValidationError("state values are out of range or unavailable")
        if (state.device_id.device!=self.device or state.device_id.dtype!=torch.int64
                or tuple(state.device_id.shape)!=(n,) or bool((state.device_id!=self.controller._device_id).any())):
            raise StateValidationError("state device_id mismatch")

    def decode_joint_targets(self,state):
        self._validate_state(state)
        values=state.values.to(torch.float64)
        result={}
        c=self.controller
        for mapping in c.axis_mappings:
            value=values[:,self.channels[mapping.channel]]
            result[mapping.source]=value*torch.where(value<0,torch.full_like(value,-mapping.lower),torch.full_like(value,mapping.upper))
        for mapping in c.scalar_mappings:
            result[mapping.source]=mapping.lower+values[:,self.channels[mapping.channel]]*(mapping.upper-mapping.lower)
        for mapping in c.split_mappings:
            signed=(values[:,self.channels[mapping.positive_channel]]-values[:,self.channels[mapping.negative_channel]]).clamp(-1,1)
            result[mapping.source]=signed*torch.where(signed<0,torch.full_like(signed,-mapping.lower),torch.full_like(signed,mapping.upper))
        packed=torch.stack(tuple(result.values()),dim=1) if result else values[:,:0]
        return NamedJointBatch(tuple(result),packed.to(self.dtype))

    def decode_event_targets(self,events):
        self._check(events,len(self.event_names))
        if bool(((events<0)|(events>1)).any()):
            raise StateValidationError("events must be within [0,1]")
        result={mapping.source:mapping.lower+events[:,i].to(torch.float64)*(mapping.upper-mapping.lower)
                for i,mapping in enumerate(self.controller.physical_event_mappings)}
        packed=torch.stack(tuple(result.values()),dim=1) if result else events[:,:0]
        return NamedJointBatch(tuple(result),packed.to(self.dtype))
