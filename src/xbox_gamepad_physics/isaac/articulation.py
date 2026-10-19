"""Caller-owned Isaac Lab configuration and initialized articulation binding."""
from __future__ import annotations

import math
from pathlib import Path

from ..backends.common.handle import ResetRequest, SignalHandleMixin
from ..backends.common.model import Pose, finite_value
from .constraints import require_supported_constraints, validate_initial_positions, verify_native_cones


def make_articulation_cfg(usd_path, *, motion, physical, prim_path='/World/Gamepad',
                          root_pose=Pose(), activate_contact_sensors=False):
    """Return configuration without launching, spawning, resetting or stepping.

    Root fixed/free is frozen in the USD at birth. Mass properties are authored
    in the USD, never overridden by a density/mass recomputation in this factory.
    Native actuator tensors use SI (unlike USD angular attributes).
    """
    require_supported_constraints(motion)
    validate_initial_positions(motion, physical)
    from isaaclab.assets import ArticulationCfg
    from isaaclab.actuators import ImplicitActuatorCfg
    from isaaclab.sim import UsdFileCfg
    if set(physical.return_laws) != set(motion.joint_by_name):
        raise ValueError('physical return laws and motion joint names differ')
    def values(field):
        result = {}
        for name, law in physical.return_laws.items():
            value = getattr(law, field).value
            if value is None:
                raise ValueError(f'{name}.{field}: native actuator requires a known value')
            result[name] = float(value)
        return result
    return ArticulationCfg(
        prim_path=prim_path,
        spawn=UsdFileCfg(usd_path=str(Path(usd_path).resolve()),activate_contact_sensors=activate_contact_sensors),
        init_state=ArticulationCfg.InitialStateCfg(pos=root_pose.position_m,
            rot=root_pose.orientation_wxyz, joint_pos=values('initial_position'), joint_vel={'.*': 0.}),
        soft_joint_pos_limit_factor=1.,
        actuators={'controls': ImplicitActuatorCfg(
            joint_names_expr=[j.name for j in motion.joints],
            stiffness=values('stiffness'), damping=values('drive_damping'),
            viscous_friction=values('passive_damping'),
            effort_limit_sim=values('effort_limit'), velocity_limit_sim=values('velocity_limit'))})


class IsaacGamepadHandle(SignalHandleMixin):
    """Scalar handle with native cone joints and validated explicit writes."""
    asset_id = 'xbox_one_s'
    backend = 'isaac'
    profile = 'full_controls'
    capabilities = frozenset({'named_joints', 'signals', 'birth_fixed_free'})

    def __init__(self, articulation, *, motion, physical):
        require_supported_constraints(motion)
        if not articulation.is_initialized:
            raise ValueError('bind_articulation requires an initialized caller articulation')
        if articulation.num_instances != 1:
            raise ValueError('B1 scalar binding requires one instance; batch support belongs to B2')
        names = tuple(articulation.joint_names)
        if len(names) != len(set(names)) or set(names) != set(motion.joint_by_name):
            raise ValueError('native articulation and common motion joint sets differ')
        self.articulation = articulation
        self.motion = motion
        self.physical = physical
        self._indices = {name: i for i, name in enumerate(names)}
        self._signal_controller = motion.signal_controller
        verify_native_cones(articulation, motion)
        from .shaft_limits import ShaftLimits
        self._shaft_limits = ShaftLimits(articulation, motion)
        self._shaft_limits.validate_initial_state()
        self.restore_passive_targets()

    @property
    def joint_names(self):
        return tuple(self._indices)

    @property
    def root_fixed(self):
        return bool(self.articulation.is_fixed_base)

    def joint_position(self, name):
        return float(self.articulation.data.joint_pos[0, self._indices[name]].item())

    def joint_positions(self):
        q = self.articulation.data.joint_pos[0].detach().cpu().tolist()
        return {n: float(q[i]) for n, i in self._indices.items()}

    def joint_velocity(self, name):
        return float(self.articulation.data.joint_vel[0, self._indices[name]].item())

    def _check(self, positions, *, targets=False):
        for name, value in positions.items():
            joint = self.motion.joint_by_name[name]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f'{name}: expected a finite scalar')
            if not joint.lower <= value <= joint.upper:
                # Only the explicitly evidenced preload target may exceed travel.
                if not targets or value != self.physical.return_laws[name].neutral_target.value:
                    raise ValueError(f'{name}: outside common joint limits')

    def set_joint_positions(self, positions):
        self._check(positions)
        q = self.articulation.data.joint_pos.clone()
        v = self.articulation.data.joint_vel.clone()
        for name, value in positions.items():
            q[0, self._indices[name]] = value
        q = self._shaft_limits.checked_state(q, v)
        self.articulation.write_joint_state_to_sim(q, v)

    def set_joint_target(self, name, target):
        self._check({name: target}, targets=True)
        import torch
        value = torch.tensor([[target]], device=self.articulation.device,
                             dtype=self.articulation.data.joint_pos.dtype)
        self.articulation.set_joint_position_target(value, joint_ids=[self._indices[name]])

    def restore_passive_targets(self):
        for name, law in self.physical.return_laws.items():
            self.set_joint_target(name, law.neutral_target.value)

    def root_pose(self):
        data = self.articulation.data.root_state_w[0, :7].detach().cpu().tolist()
        q=data[3:7]
        norm=math.sqrt(sum(v*v for v in q))
        return Pose(tuple(data[:3]), tuple(v/norm for v in q))

    def root_twist(self):
        return tuple(self.articulation.data.root_state_w[0, 7:13].detach().cpu().tolist())

    def reset(self, request=ResetRequest()):
        import torch
        if request.targets not in {'passive', 'retain'}:
            raise ValueError("reset targets must be 'passive' or 'retain'")
        if request.joint_positions is not None:
            self._check(request.joint_positions)
        if self.root_fixed and (request.root_pose is not None or request.root_twist is not None):
            raise ValueError('fixed roots cannot be repositioned after birth')
        if request.root_pose is not None and not isinstance(request.root_pose, Pose):
            raise ValueError('scalar reset root_pose must be a common Pose')
        if request.root_twist is not None:
            finite_value(request.root_twist)
            if len(request.root_twist) != 6:
                raise ValueError('root_twist must have six SI components')
        if request.joint_velocities is not None:
            finite_value(tuple(request.joint_velocities.values()))
        art = self.articulation
        q = art.data.joint_pos.clone()
        v = art.data.joint_vel.clone()
        positions = request.joint_positions or {n: l.initial_position.value for n,l in self.physical.return_laws.items()}
        velocities = request.joint_velocities or {n: 0. for n in self.joint_names}
        for name, value in positions.items():
            q[0, self._indices[name]] = value
        for name, value in velocities.items():
            if not math.isfinite(value):
                raise ValueError('reset velocities must be finite')
            v[0, self._indices[name]] = value
        q = self._shaft_limits.checked_state(q, v)
        # Validate the complete joint candidate before writing root or joints.
        if request.root_pose is not None:
            pose = request.root_pose
            art.write_root_pose_to_sim(torch.tensor([[*pose.position_m, *pose.orientation_wxyz]],
                device=art.device, dtype=art.data.joint_pos.dtype))
        if request.root_twist is not None:
            art.write_root_velocity_to_sim(torch.tensor([request.root_twist], device=art.device,
                dtype=art.data.joint_pos.dtype))
        art.write_joint_state_to_sim(q, v)
        art.reset()
        if request.targets == 'passive':
            self.restore_passive_targets()


def bind_articulation(articulation, *, motion, physical):
    """Bind initialized native data without taking ownership of its lifecycle."""
    return IsaacGamepadHandle(articulation, motion=motion, physical=physical)
