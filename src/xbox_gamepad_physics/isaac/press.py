"""Native adapter for the shared frozen PressExecutor protocol.

The caller owns creation, physics dt and stepping lifetime. No gamepad q or
non-passive targets are written during a press trajectory.
"""
from __future__ import annotations
import math
import torch
from ..state import CHANNEL_NAMES


class IsaacPressExecutor:
    def __init__(self,*,simulation,gamepad,probe,sensors,root_pose,radius_m,dt_s=.004):
        self.simulation=simulation;self.gamepad=gamepad;self.probe=probe
        self.sensors=sensors;self.fixture_root_pose=root_pose;self.dt_s=dt_s;self.radius_m=radius_m
        self._step_count=0
        self.diagnostic_links=[]

    def reset_case(self,suite,case):
        if case.root_pose!=self.fixture_root_pose:
            raise ValueError('fixed root differs from the pose selected at birth')
        if suite.fixture['dt_s']!=self.dt_s:
            raise ValueError('the caller must explicitly adapt the frozen physics dt')
        self.gamepad.reset()
        art=self.gamepad.articulation
        state=self.probe.data.default_root_state.clone()
        state[0,:3]=torch.tensor([s-d*.015 for s,d in zip(case.plan['start_m'],case.plan['direction'])],device=self.probe.device)
        state[0,3:7]=torch.tensor([1.,0.,0.,0.],device=self.probe.device)
        state[:,7:]=0
        self.probe.write_root_state_to_sim(state);self.probe.reset()
        for sensor in self.sensors.values():sensor.reset()
        self.case=case;self._step_count=0

    def ball_state(self):
        return {'position_m':self.probe.data.root_pos_w[0].cpu().tolist(),
                'velocity_m_s':self.probe.data.root_lin_vel_w[0].cpu().tolist()}

    def apply_ball_force(self,force_n):
        force=torch.tensor([[force_n]],dtype=torch.float32,device=self.probe.device)
        # Isaac Lab caches world->local orientation in the permanent composer.
        # Refresh it for a world-frame force after the free probe has rotated.
        self.probe.permanent_wrench_composer.reset()
        self.probe.set_external_force_and_torque(force,torch.zeros_like(force),is_global=True)

    def step(self,dt_s):
        if dt_s!=self.dt_s:raise ValueError('unexpected shared runner timestep')
        from .stepping import step
        self.probe.write_data_to_sim()
        step(self.simulation,gamepads=(self.gamepad,),render=False)
        self.probe.update(dt_s)
        for sensor in self.sensors.values():sensor.update(dt_s,force_recompute=True)
        self._step_count+=1

    def sample(self):
        q=self.gamepad.joint_positions()
        state=self.gamepad.motion.signal_controller.encode(q)
        pose=self.probe.data.root_state_w[0,:7].cpu().tolist()
        contacts=[]
        for link,sensor in self.sensors.items():
            forces=sensor.data.force_matrix_w
            if forces is None:raise RuntimeError('filtered contact force tensor is unavailable')
            force=forces.reshape(-1,3).sum(0)
            norm=float(torch.linalg.vector_norm(force).item())
            if norm>1e-6:
                points=sensor.data.contact_pos_w.reshape(-1,3)
                points=points[torch.isfinite(points).all(1)]
                point=points.mean(0).cpu().tolist() if len(points) else None
                residual=None if point is None else math.sqrt(sum((a-b)**2 for a,b in zip(pose[:3],point)))-self.radius_m
                contacts.append({'env_id':0,'link':link,'other_id':'probe','frame':'world',
                    'force_n':force.cpu().tolist(),'point_m':point,
                    'contact_point_radial_residual_m':residual,
                    'aggregation_window_s':self.dt_s})
        excess={n:max(j.lower-q[n],q[n]-j.upper,0.) for n,j in self.gamepad.motion.joint_by_name.items()}
        body_poses={}
        art=self.gamepad.articulation
        for link in self.diagnostic_links:
            i=art.body_names.index(link)
            body_poses[link]=torch.cat((art.data.body_link_pos_w[0,i],art.data.body_link_quat_w[0,i])).cpu().tolist()
        limits=self.gamepad._shaft_limits
        shaft_diagnostic=None
        if limits.limits:
            angles,jacobian=limits.geometry(art.data.joint_pos)
            outward=(jacobian*art.data.joint_vel.double()[:,None]).sum(-1)
            boundary=angles>=limits.maximum
            velocity=outward[boundary]
            shaft_diagnostic={
                'maximum_angle_rad':angles.amax(0).cpu().tolist(),
                'maximum_excess_rad':(angles-limits.maximum).clamp_min(0.).amax(0).cpu().tolist(),
                'maximum_boundary_outward_rad_s':float(velocity.max().item()) if velocity.numel() else None,
                'enforcement':'native_regular_spherical',
                'state_projection':False,
                'impulse_n_m_s':None,
                'impulse_missing_reason':'Native cone impulse is not exposed by this adapter.'}
        return {'shaft_limits':shaft_diagnostic,'diagnostic_body_link_poses':body_poses,'joint_positions':q,'signals':dict(zip(CHANNEL_NAMES,state.values)),
                'probe':{'pose':pose,'events':self.gamepad.motion.signal_controller.encode_physical_events(q)},
                'contacts':contacts,'joint_limit_excess':excess,
                'gamepad_internal_pairs':0,
                'internal_pairs_basis':'native articulation self-collisions disabled; no internal pairs can be generated',
                'root_pose':list(self.gamepad.root_pose().position_m)+list(self.gamepad.root_pose().orientation_wxyz)}
